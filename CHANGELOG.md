# Changelog

## [Unreleased]

### Breaking

- Replaced one-shot `heimdall ask` with a long-running `heimdall serve` runtime and a thin CLI client (`heimdall` / `heimdall cli`) that connects over HTTP/SSE

### Added

- `heimdall serve` FastAPI control API (SSE ask stream + HITL resume)
- Compose service runs `heimdall serve` in the background; use `docker compose exec -it heimdall heimdall` for the client REPL

### Fixed

- CLI HITL confirm uses `Выполнить? [y/N]:` without a second `heimdall>` prompt
- Thin client reads `HEIMDALL_URL` without requiring GigaChat/Postgres credentials

## [0.2.0]

### Added

- Docker multi-target images (`slim`, `embeddings`) and `compose.yml` guest setup
- GitHub Actions CI with GHCR publish on `v*` tags

## [0.1.0]

- Initial Heimdall v1 CLI agent (LangGraph, GigaChat, RAG, Loki/VM/Docker tools)
