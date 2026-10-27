# Changelog

## [Unreleased]

### Breaking

- Removed the `heimdall` console script. Start the runtime with `python -m heimdall serve` (including the image `ENTRYPOINT`). The REPL is the separate `cli` script (`uv run cli`, `docker compose exec -it heimdall cli`)
- A restart confirm accepts only latin `y` / `yes`

### Added

- Compose healthcheck: the service is healthy once `HEIMDALL_URL/health` answers
- Makefile targets for local lint, typecheck, and tests

### Fixed

- Ingest refuses a missing or empty knowledge directory and keeps the existing chunks
- REPL `ingest` prints the chunk count, and a refusal prints the server detail instead of `ClientResponseError: 400`
- GigaChat access token is reused only while more than five minutes remain, and a request is retried once after 401
- `sentence-transformers` is imported only when the local embedder loads, so CI and the slim image do not need that group

### Changed

- Split the package into application, domain, infrastructure, and presentation layers. Agent behavior is unchanged
- Serve and the CLI are separate processes. The CLI talks to the API over HTTP, and a HITL decision is a bool until the graph resumes
- Dropped the unused `CliChannel` after thin-client HITL
- A disconnected SSE ask declines the pending HITL run through `decide`
- Tunnel inventory and the restart allowlist cover 3x-ui only; sing-box is no longer part of this host's docs
- mypy typechecks langgraph imports (`py.typed` is shipped by the package)

## [0.3.0]

### Breaking

- Replaced one-shot `heimdall ask` with a long-running `heimdall serve` runtime and a thin CLI client (`heimdall` / `heimdall cli`) that connects over HTTP/SSE

### Added

- `heimdall serve` FastAPI control API (SSE ask stream + HITL resume)
- Compose service runs `heimdall serve` in the background; use `docker compose exec -it heimdall cli` for the client REPL
- Console script `cli` → same entry as `heimdall` (for `docker compose exec -it heimdall cli`)

### Fixed

- CLI HITL confirm uses `Выполнить? [y/N]:` without a second `heimdall>` prompt
- Thin client reads `HEIMDALL_URL` without requiring GigaChat/Postgres credentials

### Changed

- Compose mounts Hugging Face cache as `./data/hf` bind instead of a named volume

## [0.2.0]

### Added

- Docker multi-target images (`slim`, `embeddings`) and `compose.yml` guest setup
- GitHub Actions CI with GHCR publish on `v*` tags

## [0.1.0]

- Initial Heimdall v1 CLI agent (LangGraph, GigaChat, RAG, Loki/VM/Docker tools)
