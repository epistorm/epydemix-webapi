---
sidebar_position: 1
sidebar_label: Running the API Locally
---

# Running the API Locally

## Prerequisites

- [uv](https://docs.astral.sh/uv/) or Docker

## With uv

```bash
git clone https://github.com/epistorm/epydemix-webapi.git
cd epydemix-webapi
uv sync
uv run uvicorn app.main:app --reload
```

The API is now running at `http://localhost:8000`.

After pulling an update, run `uv sync --locked` and restart the server to use
the dependencies recorded in `uv.lock`.

## With Docker Compose

```bash
docker compose up
```

For hot reload during development:

```bash
docker compose --profile dev up api-dev
```

## Check it's working

```bash
curl http://localhost:8000/api/v1/health
```

```json
{"status": "healthy", "version": "0.11.0", "epydemix_version": "1.4.0"}
```

Swagger UI is available at `http://localhost:8000/api/v1/docs`.
