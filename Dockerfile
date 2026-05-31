# Frontend build stage
FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

# Build stage
FROM python:3.12-slim AS builder

# Set build arguments
ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_NO_CACHE_DIR=1
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Configure apt for reliability
RUN echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/80-retries \
    && echo 'APT::Install-Recommends "false";' > /etc/apt/apt.conf.d/80-recommends \
    && echo 'APT::Get::Assume-Yes "true";' > /etc/apt/apt.conf.d/80-assume-yes \
    && echo 'Acquire::http::Pipeline-Depth "0";' > /etc/apt/apt.conf.d/80-pipeline-depth \
    && echo 'Acquire::http::No-Cache=True;' > /etc/apt/apt.conf.d/80-no-cache \
    && echo 'Acquire::BrokenProxy=true;' > /etc/apt/apt.conf.d/80-broken-proxy

# Install build dependencies with retry mechanism
RUN set -eux; \
    apt-get update -y; \
    for i in $(seq 1 3); do \
        apt-get install -y --no-install-recommends \
            build-essential \
            python3-dev \
        && break \
        || { echo "Retry attempt $i"; sleep 5; }; \
    done; \
    rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies first
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy the rest of the application
COPY pyproject.toml .
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/
COPY infra/scripts/entrypoint.sh ./entrypoint.sh

# Install the application
RUN pip install --no-cache-dir .

# Pre-download tokenizer into a fixed path that the runtime stage can copy
ENV HF_HOME=/build/.cache/huggingface
RUN python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('BAAI/bge-m3', local_files_only=False)"

# Runtime stage
FROM python:3.12-slim

# Set runtime arguments
ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Copy installed packages, application files, and pre-downloaded tokenizer cache
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /build/src /app/src
COPY --from=builder /build/pyproject.toml /app/pyproject.toml
COPY --from=builder /build/alembic.ini /app/alembic.ini
COPY --from=builder /build/alembic /app/alembic
COPY --from=builder /build/.cache/huggingface /app/.cache/huggingface
COPY --from=frontend-builder /frontend/dist /app/src/frontend/dist

# Set environment variables
ENV PYTHONPATH=/app/src:$PYTHONPATH \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8081 \
    HF_HOME=/app/.cache/huggingface

# Install runtime dependencies with retry mechanism
RUN set -eux; \
    apt-get update -y; \
    for i in $(seq 1 3); do \
        apt-get install -y --no-install-recommends \
            curl \
            libmagic1 \
        && break \
        || { echo "Retry attempt $i"; sleep 5; }; \
    done; \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT}/health || exit 1

COPY --from=builder --chown=appuser:appuser /build/entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# Command to run the application
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.app_fastapi:app", "--host", "0.0.0.0", "--port", "8081"]
