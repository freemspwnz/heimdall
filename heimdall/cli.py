import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

import asyncpg
import uvicorn
from langgraph.types import Command

from heimdall.api.app import create_app
from heimdall.channels import CliChannel, UserChannel
from heimdall.graph import CompiledGraph, GraphState, build_graph
from heimdall.providers import ChatUnavailable, EmbeddingsUnavailable
from heimdall.rag import PgVectorStore, ingest_knowledge
from heimdall.runtime.deps import (
    AppDeps,
    docker_connector,
    ingest_production_deps,
    parse_listen,
    production_deps,
)
from heimdall.runtime.runner import AskRunner
from heimdall.runtime.state import (
    is_interrupted,
    pending_action,
    report,
    text,
)
from heimdall.settings import Settings

_is_interrupted = is_interrupted
_pending_action = pending_action
_report = report
_text = text

# Re-export for tests and callers that import from cli.
_docker_connector = docker_connector
_production_deps = production_deps
_ingest_production_deps = ingest_production_deps

CHAT_UNAVAILABLE = "модель недоступна"
EMBEDDINGS_UNAVAILABLE = "эмбеддинги недоступны"
INGESTED = "Проиндексировано фрагментов"
STORE_UNAVAILABLE = (
    "база знаний недоступна, проверьте postgres и выполните heimdall ingest"
)
RUN_FAILED = "не удалось выполнить проверку"
STARTUP_FAILED = "не удалось запустить агента, проверьте .env и доступность сервисов"
INGEST_FAILED = "не удалось проиндексировать базу знаний"
BROKEN_PROPOSAL = "агент предложил действие, которое не удалось разобрать"
STILL_INTERRUPTED = "агент снова ждёт подтверждения, отчёт не готов"
RESTART_ALREADY_RAN = "Рестарт уже выполнен"
RESTART_OK = "успешно"
RESTART_FAILED = "с ошибкой"  # noqa: RUF001
REPL_PROMPT = "heimdall> "
REPL_EXIT_WORDS = frozenset({"exit", "quit"})


def main(
    argv: list[str] | None = None,
    deps: AppDeps | None = None,
    *,
    channel: UserChannel | None = None,
) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if args.command == "serve":
        return asyncio.run(run_serve())
    if args.command == "ask":
        return asyncio.run(_ask(args.question, deps, channel))
    if args.command == "ingest":
        return asyncio.run(_ingest(deps))
    return asyncio.run(_repl(deps, channel))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heimdall",
        description="DevOps agent for a homelab",
    )
    commands = parser.add_subparsers(dest="command", required=False)
    ask = commands.add_parser("ask", help="diagnose a problem in the homelab")
    ask.add_argument("question", help="question in free form")
    commands.add_parser("ingest", help="index the knowledge base")
    commands.add_parser("serve", help="run the agent control API")
    return parser


def _read_repl_line() -> str | None:
    try:
        return input(REPL_PROMPT)
    except EOFError:
        return None


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


async def _ask(
    question: str,
    deps: AppDeps | None,
    channel: UserChannel | None,
) -> int:
    if deps is not None:
        return await _run_ask(question, deps, channel)
    return await _in_production(
        lambda production: _run_ask(question, production, channel),
        _production_deps,
    )


async def _ingest(deps: AppDeps | None) -> int:
    if deps is not None:
        return await _run_ingest(deps)
    return await _in_production(_run_ingest, _ingest_production_deps)


async def _repl(deps: AppDeps | None, channel: UserChannel | None) -> int:
    if deps is not None:
        return await _run_repl(deps, channel)
    return await _in_production(
        lambda production: _run_repl(production, channel),
        _production_deps,
    )


async def _run_repl(deps: AppDeps, channel: UserChannel | None) -> int:
    graph = build_graph(
        retriever=deps.store,
        embedder=deps.embedder,
        chat=deps.chat,
        docker=deps.docker,
        loki=deps.loki,
        vm=deps.vm,
        checkpointer=deps.checkpointer,
    )
    while True:
        raw = _read_repl_line()
        if raw is None:
            return 0
        question = raw.strip()
        if not question:
            continue
        if question.lower() in REPL_EXIT_WORDS:
            return 0
        await _run_ask_with_graph(question, graph, channel)


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


async def _run_ask(
    question: str,
    deps: AppDeps,
    channel: UserChannel | None,
) -> int:
    graph = build_graph(
        retriever=deps.store,
        embedder=deps.embedder,
        chat=deps.chat,
        docker=deps.docker,
        loki=deps.loki,
        vm=deps.vm,
        checkpointer=deps.checkpointer,
    )
    return await _run_ask_with_graph(question, graph, channel)


async def _run_ask_with_graph(
    question: str,
    graph: CompiledGraph,
    channel: UserChannel | None,
) -> int:
    ch = channel if channel is not None else CliChannel()
    thread = {"thread_id": str(uuid4())}
    try:
        state = dict(
            await graph.ainvoke(_initial_state(question), {"configurable": thread})
        )
        if _is_interrupted(state):
            action = _pending_action(state)
            if action is None:
                ch.emit(BROKEN_PROPOSAL)
                return 1
            decision = "yes" if ch.confirm(action) else "no"
            state = dict(
                await graph.ainvoke(Command(resume=decision), {"configurable": thread})
            )
            if _is_interrupted(state):
                ch.emit(STILL_INTERRUPTED)
                return 1
    except ChatUnavailable:
        return await _fail(graph, thread, ch, CHAT_UNAVAILABLE)
    except asyncpg.PostgresError as exc:
        return await _fail(graph, thread, ch, f"{STORE_UNAVAILABLE}: {exc}")
    except Exception as exc:
        return await _fail(graph, thread, ch, f"{RUN_FAILED}: {exc}")
    ch.emit(_report(state))
    return 0


async def _fail(
    graph: CompiledGraph,
    thread: dict[str, str],
    channel: UserChannel,
    reason: str,
) -> int:
    note = await _execution_note(graph, thread)
    if note is not None:
        channel.emit(note)
    channel.emit(reason)
    return 1


async def _execution_note(graph: CompiledGraph, thread: dict[str, str]) -> str | None:
    try:
        snapshot = await graph.aget_state({"configurable": thread})
    except Exception:
        return None
    values = getattr(snapshot, "values", None)
    if not isinstance(values, dict):
        return None
    result = values.get("execution_result")
    if not isinstance(result, dict):
        return None
    action = values.get("proposed_action")
    target = _text(action.get("target")) if isinstance(action, dict) else ""
    if result.get("ok"):
        outcome = RESTART_OK
    else:
        outcome = f"{RESTART_FAILED}: {_text(result.get('error'))}"
    return f"{RESTART_ALREADY_RAN}: {target} ({outcome})."


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


def _initial_state(question: str) -> GraphState:
    return GraphState(
        question=question,
        retrieved_chunks=[],
        observations=[],
        hypothesis=None,
        confidence=None,
        investigate_rounds=0,
        proposed_action=None,
        human_decision=None,
        execution_result=None,
        report=None,
    )
