# Production

## Fly.io

The project includes a `fly.toml` configuration. Make sure [flyctl](https://fly.io/docs/hands-on/install-flyctl/) is installed and you're logged in.

```bash
fly auth login
fly deploy
```

## Docker

Build and run the production image:

```bash
docker build -t epydemix-api .
docker run -p 8000:8000 epydemix-api
```

## Google Cloud Run

Deploy from source with Cloud Build:

```bash
gcloud run deploy epydemix-api --source . --region=us-east1 \
  --cpu=2 --concurrency=2 --max-instances=20 --allow-unauthenticated
```

The simulation endpoint is CPU-bound, so set `--concurrency` to match the worker/vCPU
count, otherwise requests queue on an overloaded instance instead of scaling out. See
[Google Cloud Run](./google-cloud-run.md) for the full guide and tuning rationale.

## Environment variables

See [Configuration](/docs/reference/configuration) for all available settings.
