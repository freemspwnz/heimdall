# Heimdall

Open-source DevOps agent for a homelab.

You ask a question in the CLI. Heimdall looks up your runbooks (RAG), queries Loki, VictoriaMetrics, and Docker, then returns a short diagnosis. If a restart looks like the fix, it prints the exact command and waits for `y`/`n`. It never restarts anything on its own.

v1 is a local CLI on the same host as the stack. No SSH, no Telegram, no unrestricted shell. RAG is your inventory and a few runbooks, not upstream wikis.

## Stack

- Python 3.12+, asyncio, LangGraph, uv
- GigaChat for chat and embeddings
- pgvector in a dedicated `heimdall` database on the existing Postgres
- aiohttp clients for Loki and VictoriaMetrics
- Docker Engine API via the local Unix socket

## Setup

```bash
uv sync --group dev
cp .env.example .env
# fill GIGACHAT_CREDENTIALS and POSTGRES_DSN (and URLs if needed)
```

Create a dedicated database and enable pgvector (as a Postgres superuser):

```sql
CREATE DATABASE heimdall;
\c heimdall
CREATE EXTENSION vector;
```

Index the knowledge base, then ask:

```bash
uv run heimdall ingest
uv run heimdall ask "Что с postgres?"
```

### Example questions

```bash
uv run heimdall ask "Что с postgres?"
uv run heimdall ask "Почему не открывается сервис за Traefik?"
uv run heimdall ask "Почему отвалился туннель?"
```

### HITL

If Heimdall proposes a restart, it prints `docker restart <name>` with reason and risk, then waits on stdin. Type `y` or `yes` to apply; anything else (including empty input) skips the restart. Only allowlisted containers can be restarted (`postgres`, `traefik`, `whoami`, `sing-box`, `3x-ui`). `vaultwarden` is never restartable.

## Tests and quality gate

Unit tests use fakes — **no live GigaChat, Loki, Docker daemon, or Postgres** in CI/local pytest.

```bash
uv run pytest && uv run mypy heimdall && uv run ruff check heimdall tests
```

## Commands

| Command | Purpose |
| --- | --- |
| `uv run heimdall ingest` | Chunk and embed `docs/knowledge` into pgvector |
| `uv run heimdall ask "..."` | Run the diagnostic graph for one question |
