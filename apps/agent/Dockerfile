FROM python:3.12-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PIP_NO_CACHE_DIR=1
RUN pip install uv==0.13.9
WORKDIR /app/apps/agent
COPY apps/agent/pyproject.toml apps/agent/uv.lock apps/agent/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/agent/src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
ENV PATH="/app/apps/agent/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --home /app app
WORKDIR /app/apps/agent
COPY --from=builder /app/apps/agent /app/apps/agent
COPY apps/agent/alembic.ini ./alembic.ini
COPY apps/agent/migrations ./migrations
COPY workspaces /app/workspaces
COPY db /app/db
# Cache of the embedding model (a named volume in compose); the model is downloaded on first use.
# HF_HOME keeps the Hugging Face client's own cache and logs inside the volume too: the container
# runs as a system user whose HOME (/app) is not writable.
ENV HF_HOME=/var/cache/fastembed/hf
RUN mkdir -p /var/cache/fastembed && chown app /var/cache/fastembed
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn lead_qualifier.entrypoint:app --host 0.0.0.0 --port 8000 --no-proxy-headers"]
