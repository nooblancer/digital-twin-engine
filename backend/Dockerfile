# Multi-stage Dockerfile for Digital Twin Telemetry Engine services.
# All services share this image; the specific service is selected via
# the CMD/entrypoint at runtime in docker-compose.yml.

FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies needed by numpy/scipy/torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir .

# Copy application source
COPY digital_twin_engine/ ./digital_twin_engine/

# Default healthcheck (overridden per-service in compose)
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

EXPOSE 8080
