# Build stage
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml uv.lock .python-version README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ ./app/

# Runtime stage
FROM python:3.13-slim

WORKDIR /app

# Install only runtime dependencies (libopenblas for numpy/scipy)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libopenblas0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy venv and app from builder
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/app app

# Expose port
EXPOSE 8000

# Run with uvicorn. Listen on $PORT (Cloud Run injects it, default 8080) and fall back
# to 8000 elsewhere (Fly.io, docker-compose, local). sh -c expands the env var; exec
# replaces the shell so signals reach uvicorn.
CMD ["sh", "-c", "exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
