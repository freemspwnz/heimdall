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

# Install the project into the venv. --reinstall-package heimdall forces a
# fresh build even when the BuildKit uv cache still has an old project wheel
# (otherwise site-packages stays stale while /app/heimdall looks new).
# Drop the source tree after sync so `import heimdall` always hits site-packages
# (cwd /app would otherwise shadow with a second copy).
# --- deps (slim): project + default groups, no embeddings ---
FROM base AS deps-slim
COPY pyproject.toml uv.lock README.md ./
COPY heimdall ./heimdall
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --reinstall-package heimdall \
    && rm -rf /app/heimdall

# --- deps (embeddings): add embeddings group (CPU torch via uv index) ---
FROM base AS deps-embeddings
COPY pyproject.toml uv.lock README.md ./
COPY heimdall ./heimdall
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --reinstall-package heimdall \
        --group embeddings \
    && rm -rf /app/heimdall

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
