# World Cup Oracle — Docker Deployment Template
#
# TEMPLATE ONLY — not a verified production deployment.
# Default mode: OFFLINE.  Live features require explicit opt-in + credentials.
#
# Build:
#   docker build -t world-cup-oracle:latest -f deploy/docker/Dockerfile .
#
# Run (offline default):
#   docker run --rm world-cup-oracle:latest python -m oracle_core.real_match_cli \
#     --home "Team A" --away "Team B"
#
# Run (with live config, requires env vars):
#   docker run --rm \
#     -e WORLD_CUP_ORACLE_RUNTIME_MODE=live_opt_in \
#     -e WORLD_CUP_ORACLE_NETWORK_ALLOWED=true \
#     --env-file deploy/env/.env \
#     world-cup-oracle:latest python -m oracle_core.production_health

FROM python:3.11-slim

LABEL org.opencontainers.image.title="World Cup Oracle"
LABEL org.opencontainers.image.description="Production-oriented MVP — NOT full production"
LABEL org.opencontainers.image.version="v2.4-p36.1"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY oracle_core/ ./oracle_core/
COPY oracle_training/ ./oracle_training/
COPY football_data/ ./football_data/
COPY knowledge/ ./knowledge/

# Default: offline mode
ENV WORLD_CUP_ORACLE_RUNTIME_MODE=offline
ENV WORLD_CUP_ORACLE_NETWORK_ALLOWED=false
ENV WORLD_CUP_ORACLE_ENV_ACCESS_ALLOWED=false
ENV PYTHONUNBUFFERED=1

# Healthcheck (offline by default, no network)
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -m oracle_core.production_health || exit 1

# No default command — require explicit invocation
CMD ["python", "-m", "oracle_core.production_health"]
