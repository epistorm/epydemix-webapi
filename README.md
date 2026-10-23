# epydemix WebAPI

REST API for running epidemic simulations on [epydemix](https://github.com/epistorm/epydemix).

Documentation and API reference: https://epydemix-webapi.vercel.app/docs

## Quick Start

```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn app.main:app --reload

# Run tests
uv run pytest
```

## API Endpoints

- `POST /api/v1/simulations` - Run epidemic simulation
- `POST /api/v1/simulations/export/python` - Export a simulation as executable Python
- `GET /api/v1/populations` - List available populations
- `GET|POST /api/v1/populations/export/python` - Export population discovery or custom setup
- `GET /api/v1/populations/{name}` - Get population details
- `GET /api/v1/populations/{name}/export/python` - Export population loading
- `GET /api/v1/populations/{name}/contacts` - Get contact matrices
- `GET /api/v1/populations/{name}/contacts/export/python` - Export contact-matrix loading
- `GET /api/v1/models/presets` - List model presets
- `GET /api/v1/models/presets/{name}/export/python` - Export a preset model
- `GET /api/v1/health` - Health check

## Docker

```bash
# Build and run
docker compose up

# Development with hot reload
docker compose --profile dev up api-dev
```

## Examples

```bash
# List available populations
curl http://localhost:8000/api/v1/populations

# Run SIR simulation
curl -X POST http://localhost:8000/api/v1/simulations \
  -H "Content-Type: application/json" \
  -d '{
    "model": {"preset": "SIR"},
    "population": {"name": "United_States"},
    "simulation": {
      "start_date": "2024-01-01",
      "end_date": "2024-03-01",
      "Nsim": 100
    }
  }'
```

## Documentation

API documentation and reference is available [here](https://epydemix-webapi.vercel.app/docs).

Most API parameters follow epydemix conventions. Refer to the [epydemix documentation](https://epydemix.readthedocs.io/en/latest/) for details on model parameters, population data, and simulation options.
