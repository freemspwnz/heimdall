# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- deps (slim): project + default groups, no embeddings ---
FROM base AS deps-slim
COPY pyproject.toml uv.lock README.md ./
COPY heimdall ./heimdall
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- deps (embeddings): add embeddings group (CPU torch via uv index) ---
FROM base AS deps-embeddings
COPY pyproject.toml uv.lock README.md ./
COPY heimdall ./heimdall
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --group embeddings

FROM deps-slim AS slim
ENV PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /data/hf
ENTRYPOINT ["heimdall"]
CMD ["--help"]

FROM deps-embeddings AS embeddings
ENV PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /data/hf
ENTRYPOINT ["heimdall"]
CMD ["--help"]
