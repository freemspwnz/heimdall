# Changelog

## [0.4.0]

### Breaking

- Removed the `heimdall` console script. Start the runtime with `python -m heimdall serve` (including the image `ENTRYPOINT`). The REPL is the separate `cli` script (`uv run cli`, `docker compose exec -it heimdall cli`)
- A restart confirm accepts only latin `y` / `yes`

### Added

- Compose healthcheck: the service is healthy once `HEIMDALL_URL/health` answers
- Makefile targets for local lint, typecheck, and tests
- Server logging for model requests/responses, tool observations, and the context the model saw
- `classify` picks `question_kind` (`meta` / `status` / `diagnose` / `action`) and runbook file names in one call
- Report-only path: `meta` / `status` finish in `answer` without propose or HITL
- `investigation_notes` keep investigate's final prose for diagnose, propose, and answer
- File-by-source retrieve: selected runbooks load whole from disk; vector search is fallback only
- `preflight` runs closed `heimdall-calls` fences from disk-loaded runbooks before investigate (outside the per-round tool budget)
- Demo `heimdall-calls` examples plus `host` / `redis` runbooks under `docs/knowledge`
- Vector store can list indexed chunks in ingest order

### Fixed

- Ingest refuses a missing or empty knowledge directory and keeps the existing chunks
- REPL `ingest` prints the chunk count, and a refusal prints the server detail instead of `ClientResponseError: 400`
- GigaChat access token is reused only while more than five minutes remain, and a request is retried once after 401
- `sentence-transformers` is imported only when the local embedder loads, so CI and the slim image do not need that group
- Restart only when this turn's `docker inspect` shows the target down (exited / dead / restarting / unhealthy); never restart `postgres`, `redis`, `traefik`, `3x-ui`, or `adguardhome`
- Observations record the tool name plus target / query / window so later nodes can match facts to a container
- Docker inspect observations keep container state instead of the full inspect blob
- Loki log lines keep the container label
- Compose joins the monitoring network; listen address and client URL follow the environment
- Report prompt asks for status on informational questions
- Dropped hard-coded tunnel disclaimer and prompt rules; limits live in runbooks
- REPL Cyrillic editing: `readline` plus UTF-8 locale in the image (no `PYTHONIOENCODING`)
- Skip a second investigate round when notes exist but no new observations arrived
- Skip undecodable runbook files when building the classify catalog

### Changed

- Split the package into application, domain, infrastructure, and presentation layers. Agent behavior is unchanged
- Serve and the CLI are separate processes. The CLI talks to the API over HTTP, and a HITL decision is a bool until the graph resumes
- Dropped the unused `CliChannel` after thin-client HITL
- A disconnected SSE ask declines the pending HITL run through `decide`
- Tunnel inventory and the restart allowlist cover 3x-ui only; sing-box is no longer part of this host's docs
- mypy typechecks langgraph imports (`py.typed` is shipped by the package)
- Graph path is `retrieve → preflight → investigate`; a diagnose retry re-enters investigate without preflight

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
