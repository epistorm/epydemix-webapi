---
sidebar_position: 1
sidebar_label: Google Cloud Run
---

# Google Cloud Run

This page covers deploying the API to Cloud Run, including the settings that matter for
performance under concurrent load. The recommended settings were validated by load
testing: tuning request concurrency alone gave roughly a 13x throughput and 10x latency
improvement.

## Prerequisites

- The [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated (`gcloud auth login`).
- A GCP project with billing enabled.
- The required APIs enabled
```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com --project=YOUR_PROJECT
```

## Container port

The image listens on the port given by the `PORT` environment variable, falling back to
8000 elsewhere. Cloud Run sets `PORT` automatically (8080 by default), so the container
just works with no extra flag.

## Deploy from source

`--source` uploads the repo, builds the image with Cloud Build using the Dockerfile,
pushes it to Artifact Registry, then deploys. No local Docker is needed.

```bash
gcloud run deploy epydemix-api \
  --source . \
  --project=YOUR_PROJECT \
  --region=us-east1 \
  --cpu=2 --memory=2Gi \
  --concurrency=2 \
  --min-instances=1 --max-instances=20 \
  --timeout=120 \
  --allow-unauthenticated
```

On success it prints the service URL, for example
`https://epydemix-api-XXXXXXXXX.us-east1.run.app`.

## Performance tuning

The simulation endpoint is CPU-bound. One SIR simulation (Nsim=20) takes about 1.5s, and
each uvicorn worker runs one at a time. With 2 workers on 2 vCPUs, a single instance sustains about
1.3 simulations per second.

- **`--concurrency=2`** is the key setting and must match the worker and vCPU count. The
  Cloud Run default is 80, which routes up to 80 simulations to one 2-worker instance.
  They queue behind the workers and latency climbs to 30 to 60 seconds. Setting
  concurrency to 2 means each instance only takes what it can run in parallel, so Cloud
  Run scales out to more instances instead of overloading one.
- **`--cpu=2`** must agree with uvicorn `--workers 2`. More workers than vCPUs only
  time-share the CPU and add no throughput.
- **`--max-instances=20`** sets the throughput ceiling: 20 instances times ~1.3/s is
  about 26 simulations per second. Raise it if you need more.
- **`--min-instances=1`** keeps a warm instance so the first request avoids a cold start
  (container boot, epydemix import, population cache warm). Set it higher before a known
  spike such as a workshop.
- **`--timeout=120`** is the Cloud Run request timeout. The app also self-limits to 60s.

## Verify

```bash
URL=https://epydemix-api-XXXXXXXXX.us-east1.run.app
curl -s "$URL/api/v1/health"
```

A single SIR simulation (Nsim=20) should return HTTP 200 in about 1.5s.

## Cost management

`--min-instances=1` keeps a container running continuously, which bills around the clock.
When not actively serving, scale to zero or delete:

```bash
# scale to zero (keep the service, stop idle billing):
gcloud run services update epydemix-api --project=YOUR_PROJECT --region=us-east1 --min-instances=0

# delete entirely:
gcloud run services delete epydemix-api --project=YOUR_PROJECT --region=us-east1
```

## Redeploy a prebuilt image

To redeploy with changed settings without rebuilding, point at the existing image in
Artifact Registry:

```bash
gcloud run deploy epydemix-api \
  --image us-east1-docker.pkg.dev/YOUR_PROJECT/cloud-run-source-deploy/epydemix-api:latest \
  --project=YOUR_PROJECT --region=us-east1 \
  --cpu=2 --memory=2Gi --concurrency=2 \
  --min-instances=1 --max-instances=20 --timeout=120 --allow-unauthenticated
```

## Terraform

Terraform does not build images. Build and push first
(`gcloud builds submit --tag ...` or `docker push`), then reference the image:

```hcl
resource "google_cloud_run_v2_service" "api" {
  name     = "epydemix-api"
  location = "us-east1"

  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 20
    }
    max_instance_request_concurrency = 2   # the key knob
    timeout                          = "120s"

    containers {
      image = "us-east1-docker.pkg.dev/YOUR_PROJECT/REPO/epydemix-api:latest"
      resources {
        limits = { cpu = "2", memory = "2Gi" }
      }
    }
  }
}
```
