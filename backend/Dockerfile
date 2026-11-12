# AgentGuard backend image.
#
# The backend is a FastAPI application backed by SQLAlchemy. It runs on SQLite
# by default (sufficient for a single-node demo) and can be pointed at
# PostgreSQL with AGENTGUARD_DATABASE_URL.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTGUARD_HOST=0.0.0.0 \
    AGENTGUARD_PORT=8000 \
    AGENTGUARD_DATABASE_URL=sqlite:///./data/agentguard.db \
    AGENTGUARD_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080

WORKDIR /app

# Build tooling is needed for any dependency that compiles a wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so this layer is cached across code changes.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" \
       "SQLAlchemy>=2.0" "pydantic>=2.7" "pydantic-settings>=2.2" "httpx>=0.27"

# Application code.
COPY app ./app
COPY scripts ./scripts
COPY sdk/python/agentguard ./sdk/agentguard

# SQLite data lives on a volume so it survives container restarts.
RUN useradd --create-home --shell /bin/bash agentguard \
    && mkdir -p /app/data \
    && chown -R agentguard:agentguard /app
VOLUME ["/app/data"]

USER agentguard
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
