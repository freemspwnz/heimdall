# Heimdall

Open-source DevOps agent for a homelab.

You ask a question in the CLI (`What's wrong with Postgres?`, `Why is this Traefik route down?`). Heimdall looks up your runbooks, queries Loki, VictoriaMetrics, and Docker, then returns a short diagnosis. If a restart looks like the fix, it prints the command and waits for `y`/`n`. It never restarts anything on its own.

## Status

Implementation has not started.

v1 is a local CLI on the same host as the stack. No SSH, no Telegram, no unrestricted shell. RAG is your inventory and a few runbooks, not upstream wikis.

## Planned stack

- Python, asyncio, LangGraph
- GigaChat for chat and embeddings (`POST /embeddings`)
- pgvector in a dedicated `heimdall` database on the existing Postgres
- aiohttp clients for Loki and VictoriaMetrics
- Docker Engine API via the local socket
