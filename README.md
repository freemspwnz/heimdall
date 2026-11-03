# Heimdall

[![CI](https://github.com/freemspwnz/heimdall/actions/workflows/ci.yml/badge.svg)](https://github.com/freemspwnz/heimdall/actions/workflows/ci.yml)

Open-source DevOps agent for a homelab.

You ask a question in the CLI. Heimdall classifies the question, loads the matching runbooks from disk, optionally runs their `heimdall-calls` checklists before the model loop, then may query Loki, VictoriaMetrics, and Docker. Status and meta questions get a short report without a restart proposal. If a restart still looks like the fix, it prints the exact command and waits for latin `y` / `yes`. It never restarts anything on its own.

v1 is a local agent on the same host as the stack (`serve` + thin CLI). No SSH, no Telegram, no unrestricted shell. Knowledge is your inventory and runbooks — not upstream wikis. Vector search is only a fallback when no runbook file was loaded.

## Stack

- Python 3.12+, asyncio, LangGraph, uv
- GigaChat-3-Ultra for chat via `api.giga.chat`; local `sentence-transformers` embeddings (`intfloat/multilingual-e5-base` by default)
- pgvector in a dedicated `heimdall` database on the existing Postgres
- aiohttp clients for Loki and VictoriaMetrics
- Docker Engine API via the local Unix socket (`DOCKER_HOST=unix://…` only)

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

Start the runtime, open a client REPL, then index the knowledge base from that REPL:

```bash
uv run python -m heimdall serve   # long-running runtime (loads the model once)
# other terminal:
uv run cli     # REPL → HEIMDALL_URL
# at the heimdall> prompt:
ingest
```

## Knowledge and `heimdall-calls`

Mount or set `KNOWLEDGE_DIR` (Compose default: `./docs/knowledge` → `/app/docs/knowledge`). Layout:

- `inventory.md` — service passport for ingest / context
- `runbooks/*.md` — one file per topic; `classify` picks names from this catalog

Selected runbooks are read **whole from disk** into the graph. Embeddings search runs only if no file loaded.

Optional closed fences in a runbook are executed once per question in `preflight`, before investigate, outside the model's tool budget. Closed fences are stripped from the text the model sees; unclosed fences are left in place and recorded as errors.

````markdown
```heimdall-calls
docker_inspect name=postgres
loki_query query={container_name="postgres"} since=30m
vm_query query=pg_up
```
````

One tool name per line; `key=value` args (quotes keep spaces). Use the Loki label your lab actually scrapes (`container_name` on this host). Demo fences live under `docs/knowledge`; production copies often live beside the host (for example `dev/knowledge`) and are bind-mounted the same way. Fence is optional — not every runbook needs one.

`ingest` still indexes the tree for the search fallback. After adding or changing runbook **files** for file-by-source / fences, a restart is enough for disk reads; re-`ingest` only if you care about the vector index.

## Docker / Compose (guest)

Run Heimdall as a container attached to your homelab Docker network instead of installing Python on the host.

**Prepare before first run:**

```bash
cp .env.example .env
mkdir -p data/hf && touch data/heimdall-checkpoints.sqlite
```

Edit `.env` for Compose: Loki, VictoriaMetrics, and Postgres URLs must use **Docker DNS names** of services on the monitoring network (e.g. `http://loki:3100`, `postgresql://…@postgres:5432/heimdall`). `127.0.0.1` works only for host `uv run`, not inside the container. See commented examples in `.env.example`.

The compose file joins an **external** network (`HEIMDALL_NETWORK`, default `monitoring`) so the guest can reach Loki, Postgres, and the rest of the stack by service name.

**Checkpoint file:** `./data/heimdall-checkpoints.sqlite` is bind-mounted into the container. Create the empty file with `touch` before the first run — otherwise Docker may create a directory at that path.

**Why SQLite for checkpoints (not Postgres/Redis):** LangGraph needs a checkpointer so HITL (`interrupt` → confirm restart → resume) survives across the pause. Postgres already holds RAG (pgvector); Redis may exist in the lab — neither is used for checkpoints on purpose. The agent can restart many containers it diagnoses, but never `postgres`, `redis`, `traefik`, `3x-ui`, or `adguardhome`. Checkpoints stay in a local SQLite file so a resume is not tied to a service the agent might restart, and no extra store is required for the long-running serve process.

**Docker socket:** Compose mounts `/var/run/docker.sock`. The container can call the full Docker Engine API on the host (list/restart containers, etc.). Treat this like giving the agent root-level control over your Docker daemon; use only on trusted homelab hosts.

**Image target:** `HEIMDALL_IMAGE_TARGET=embeddings` (default) builds/runs the image with local `sentence-transformers`. Set `HEIMDALL_IMAGE_TARGET=slim` if you use `EMBEDDER=gigachat` and do not need on-box embeddings.

**HF cache:** `./data/hf` is bind-mounted to `/data/hf` (`HF_HOME`) so Hugging Face model downloads persist across container rebuilds. Create the directory before the first run (`mkdir -p data/hf`). The whole `data/` tree is gitignored.
```bash
docker compose up -d
docker compose exec -it heimdall cli   # client REPL inside the container
# at the heimdall> prompt:
ingest
```

**Pull from GHCR** (images build and publish only on `v*` tags — not on every PR/push):

```bash
docker pull ghcr.io/freemspwnz/heimdall:v0.4.0-embeddings
docker pull ghcr.io/freemspwnz/heimdall:v0.4.0-slim
docker pull ghcr.io/freemspwnz/heimdall:embeddings
docker pull ghcr.io/freemspwnz/heimdall:latest   # slim only
```

Tag format: `vX.Y.Z-slim` and `vX.Y.Z-embeddings`, plus floating `:slim`, `:embeddings`, and `:latest` (slim).

### Example questions

In the client REPL (`heimdall>`):

```text
Что с postgres?
Как дела у redis?
Как в целом дела на хосте?
Почему не открывается сервис за Traefik?
Почему отвалился туннель?
```

### HITL

If Heimdall proposes a restart, it prints `docker restart <name>` with reason and risk, then waits on stdin. Type `y` or `yes` to apply; anything else (including empty input or Cyrillic «да») skips the restart. Any container can be restarted except `postgres`, `redis`, `traefik`, `3x-ui`, and `adguardhome`. The proposal also requires this turn's `docker inspect` to show that container as down.

## Tests and quality gate

Unit tests use fakes — **no live GigaChat, Loki, Docker daemon, or Postgres** in CI/local pytest. PR and `main` runs lint/mypy/pytest only; Docker images build on version tags.

```bash
make check
# or:
uv run pytest && uv run mypy heimdall && uv run ruff check heimdall tests
```

## Releases

When cutting a release tag (e.g. `v0.4.0`), move the `[Unreleased]` section in `CHANGELOG.md` to `## [0.4.0]` before tagging so `gh-release` can pick up the notes.

## Commands

| Command | Purpose |
| --- | --- |
| `uv run python -m heimdall serve` | Long-running agent runtime |
| `uv run cli` | Client REPL on the host |
| `docker compose exec -it heimdall cli` | Client REPL inside the container |
| `ingest` | Index knowledge, typed in the REPL after the runtime is up |
| `docker compose up -d` | Start serve |
| `make check` | Local lint, format check, mypy, pytest |
