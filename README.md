# Heimdall

[![CI](https://github.com/freemspwnz/heimdall/actions/workflows/ci.yml/badge.svg)](https://github.com/freemspwnz/heimdall/actions/workflows/ci.yml)

Open-source DevOps agent for a homelab.

You ask a question in the CLI. Heimdall looks up your runbooks (RAG), queries Loki, VictoriaMetrics, and Docker, then returns a short diagnosis. If a restart looks like the fix, it prints the exact command and waits for `y`/`n`. It never restarts anything on its own.

v1 is a local CLI on the same host as the stack. No SSH, no Telegram, no unrestricted shell. RAG is your inventory and a few runbooks, not upstream wikis.

## Stack

- Python 3.12+, asyncio, LangGraph, uv
- GigaChat-3-Ultra for chat via `api.giga.chat`; local `sentence-transformers` embeddings (`intfloat/multilingual-e5-base` by default)
- pgvector in a dedicated `heimdall` database on the existing Postgres
- aiohttp clients for Loki and VictoriaMetrics
- Docker Engine API via the local Unix socket

## Setup (host)

```bash
uv sync --group dev --group embeddings
cp .env.example .env
# fill GIGACHAT_CREDENTIALS and POSTGRES_DSN (and URLs if needed)
```

Torch is pinned to the **CPU** wheel (no CUDA) — suitable for hosts like Intel N100. `EMBEDDER=local` (default) uses `LOCAL_EMBEDDER_MODEL`. First run downloads the model from Hugging Face (~1 GB). Set `EMBEDDER=gigachat` only if your GigaChat plan includes embeddings.

Create a dedicated database and enable pgvector (as a Postgres superuser):

```sql
CREATE DATABASE heimdall;
\c heimdall
CREATE EXTENSION vector;
```

If you previously indexed with another embedder (e.g. GigaChat), drop the old table before re-ingest — vector dimensions differ:

```sql
DROP TABLE IF EXISTS chunks;
```

Index the knowledge base, then ask:

```bash
uv run heimdall ingest
uv run heimdall ask "Что с postgres?"
```

## Docker / Compose (guest)

Run Heimdall as a container attached to your homelab Docker network instead of installing Python on the host.

**Prepare before first run:**

```bash
cp .env.example .env
mkdir -p data && touch data/heimdall-checkpoints.sqlite
```

Edit `.env` for Compose: Loki, VictoriaMetrics, and Postgres URLs must use **Docker DNS names** of services on the lab network (e.g. `http://loki:3100`, `postgresql://…@postgres:5432/heimdall`). `127.0.0.1` works only for host `uv run`, not inside the container. See commented examples in `.env.example`.

The compose file joins an **external** network (`HEIMDALL_LAB_NETWORK`, default `lab`) so the guest can reach Loki, Postgres, and the rest of the stack by service name.

**Checkpoint file:** `./data/heimdall-checkpoints.sqlite` is bind-mounted into the container. Create the empty file with `touch` before the first run — otherwise Docker may create a directory at that path.

**Docker socket:** Compose mounts `/var/run/docker.sock`. The container can call the full Docker Engine API on the host (list/restart containers, etc.). Treat this like giving the agent root-level control over your Docker daemon; use only on trusted homelab hosts.

**Image target:** `HEIMDALL_IMAGE_TARGET=embeddings` (default) builds/runs the image with local `sentence-transformers`. Set `HEIMDALL_IMAGE_TARGET=slim` if you use `EMBEDDER=gigachat` and do not need on-box embeddings.

**HF cache:** A named volume (`hf-cache` → `/data/hf`) persists Hugging Face model downloads across container rebuilds.

```bash
docker compose run --rm -it heimdall ingest
docker compose run --rm -it heimdall ask "Что с postgres?"
```

**Pull from GHCR** (published when you push a `v*` tag):

```bash
docker pull ghcr.io/freemspwnz/heimdall:v0.2.0-embeddings
docker pull ghcr.io/freemspwnz/heimdall:v0.2.0-slim
docker pull ghcr.io/freemspwnz/heimdall:embeddings
docker pull ghcr.io/freemspwnz/heimdall:latest   # slim only
```

Tag format: `vX.Y.Z-slim` and `vX.Y.Z-embeddings`, plus floating `:slim`, `:embeddings`, and `:latest` (slim).

### Example questions

```bash
uv run heimdall ask "Что с postgres?"
uv run heimdall ask "Почему не открывается сервис за Traefik?"
uv run heimdall ask "Почему отвалился туннель?"
```

Same questions work with `docker compose run --rm -it heimdall ask "..."`.

### HITL

If Heimdall proposes a restart, it prints `docker restart <name>` with reason and risk, then waits on stdin. Type `y` or `yes` to apply; anything else (including empty input) skips the restart. Only allowlisted containers can be restarted (`postgres`, `traefik`, `whoami`, `sing-box`, `3x-ui`). `vaultwarden` is never restartable.

## Tests and quality gate

Unit tests use fakes — **no live GigaChat, Loki, Docker daemon, or Postgres** in CI/local pytest.

```bash
uv run pytest && uv run mypy heimdall && uv run ruff check heimdall tests
```

## Releases

When cutting a release tag (e.g. `v0.2.0`), move the `[Unreleased]` section in `CHANGELOG.md` to `## [0.2.0]` before tagging so `gh-release` can pick up the notes.

## Commands

| Command | Purpose |
| --- | --- |
| `uv run heimdall ingest` | Chunk and embed `docs/knowledge` into pgvector |
| `uv run heimdall ask "..."` | Run the diagnostic graph for one question |
| `docker compose run --rm -it heimdall ingest` | Same as ingest, guest container |
| `docker compose run --rm -it heimdall ask "..."` | Same as ask, guest container |
