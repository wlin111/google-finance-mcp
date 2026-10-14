# syntax=docker/dockerfile:1

# -----------------------------------------------------------------------------
# Stage 1: Build & Dependencies
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy package definition and source code
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package and runtime dependencies (including uvicorn and starlette for the SSE bridge)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . uvicorn[standard] starlette

# -----------------------------------------------------------------------------
# Stage 2: Minimal Production Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runner

WORKDIR /app

# Install curl for container health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Ensure venv binaries are on PATH
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=3000 \
    HOST=0.0.0.0

# Create non-root app user
RUN useradd -u 10001 -m -s /bin/bash appuser

# Copy bridge script
COPY bridge_sse.py /app/bridge_sse.py

RUN chown -R appuser:appuser /app
USER appuser

# Expose MCP HTTP/SSE port
EXPOSE 3000

# Docker healthcheck targeting the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:3000/health || exit 1

# Start the bridge server
CMD ["python", "bridge_sse.py"]
