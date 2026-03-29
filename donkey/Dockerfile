# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install system dependencies (build-essential for webrtcvad C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies (production only, no dev dependencies)
RUN uv sync --frozen --no-dev

# Copy application code
COPY app ./app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# API
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# 워커(같은 이미지, CMD만 교체): uv run arq app.arq_worker.WorkerSettings
