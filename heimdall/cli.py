import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

import uvicorn

from heimdall.api.app import create_app
from heimdall.client.repl import AGENT_UNAVAILABLE, run_repl
from heimdall.graph import build_graph
from heimdall.providers import EmbeddingsUnavailable
from heimdall.rag import PgVectorStore, ingest_knowledge
from heimdall.runtime.deps import (
    AppDeps,
    docker_connector,
    ingest_production_deps,
    parse_listen,
    production_deps,
)
from heimdall.runtime.runner import AskRunner
from heimdall.settings import Settings

# Re-export for tests and callers that import from cli.
_docker_connector = docker_connector
_production_deps = production_deps
_ingest_production_deps = ingest_production_deps

EMBEDDINGS_UNAVAILABLE = "эмбеддинги недоступны"
INGESTED = "Проиндексировано фрагментов"
STARTUP_FAILED = "не удалось запустить агента, проверьте .env и доступность сервисов"
INGEST_FAILED = "не удалось проиндексировать базу знаний"


def main(
    argv: list[str] | None = None,
    deps: AppDeps | None = None,
) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if args.command == "serve":
        return asyncio.run(run_serve())
    if args.command == "ingest":
        return asyncio.run(_ingest(deps))
    return asyncio.run(_run_client_repl())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heimdall",
        description="DevOps agent for a homelab",
    )
    commands = parser.add_subparsers(dest="command", required=False)
    commands.add_parser("cli", help="connect to a running agent REPL")
    commands.add_parser("ingest", help="index the knowledge base")
    commands.add_parser("serve", help="run the agent control API")
    return parser


async def _run_client_repl(settings: Settings | None = None) -> int:
    resolved = settings if settings is not None else Settings()  # type: ignore[call-arg]
    return await run_repl(resolved.heimdall_url)


async def run_serve(settings: Settings | None = None) -> int:
    resolved = settings if settings is not None else Settings()  # type: ignore[call-arg]
    async with production_deps(resolved) as deps:
        graph = build_graph(
            retriever=deps.store,
            embedder=deps.embedder,
            chat=deps.chat,
            docker=deps.docker,
            loki=deps.loki,
            vm=deps.vm,
            checkpointer=deps.checkpointer,
        )
        runner = AskRunner(graph)
        app = create_app(runner)
        host, port = parse_listen(resolved.heimdall_listen)
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
    return 0


async def _ingest(deps: AppDeps | None) -> int:
    if deps is not None:
        return await _run_ingest(deps)
    return await _in_production(_run_ingest, _ingest_production_deps)


async def _in_production(
    run: Callable[[AppDeps], Awaitable[int]],
    deps_factory: Callable[[], AbstractAsyncContextManager[AppDeps]],
) -> int:
    try:
        async with deps_factory() as production:
            return await run(production)
    except Exception as exc:
        print(f"{STARTUP_FAILED}: {exc}", file=sys.stderr)
        return 1


async def _run_ingest(deps: AppDeps) -> int:
    store = deps.store
    try:
        if isinstance(store, PgVectorStore):
            await store.ensure_schema()
        count = await ingest_knowledge(deps.knowledge_dir, store, deps.embedder)
    except EmbeddingsUnavailable:
        print(EMBEDDINGS_UNAVAILABLE)
        return 1
    except Exception as exc:
        print(f"{INGEST_FAILED}: {exc}")
        return 1
    print(f"{INGESTED}: {count}")
    return 0


# Re-export for tests that assert the message string.
__all__ = [
    "AGENT_UNAVAILABLE",
    "AppDeps",
    "main",
    "run_serve",
]
