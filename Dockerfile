# Multi-architecture production Dockerfile for QuantizedAlert (x86_64 & aarch64)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies (build-essential, git, curl, OpenMP runtime for LightGBM)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libgomp1 \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy Qlib repository if vendored, or clone shallow if absent
ARG QLIB_PATH=/app/repos/qlib
RUN mkdir -p /app/repos && \
    git clone --depth 1 https://github.com/microsoft/qlib.git /app/repos/qlib && \
    uv pip install --system --break-system-packages -e /app/repos/qlib

# Copy dependency specifications and install QuantizedAlert package
COPY pyproject.toml /app/
RUN uv pip install --system --break-system-packages -e ".[dev,billing,llm]"

# Copy source code, configurations, and database migrations
COPY src/ /app/src/
COPY config/ /app/config/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY scripts/ /app/scripts/

# Create runtime persistent state directories
RUN mkdir -p /app/data /app/market_cache /root/.qlib/qlib_data

EXPOSE 8765

# Default entrypoint runs the dashboard web server
CMD ["quantizedalert", "serve", "--host", "0.0.0.0", "--port", "8765"]

