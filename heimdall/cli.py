from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp
import asyncpg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from heimdall.channels.base import UserChannel
from heimdall.channels.cli import CliChannel
from heimdall.graph import CompiledGraph, GraphState, build_graph
from heimdall.graph.prompts import EMPTY_REPORT
from heimdall.models import Action
from heimdall.providers.gigachat import GigaChatChatModel, GigaChatEmbedder
from heimdall.providers.protocols import (
    ChatModel,
    ChatUnavailable,
    Embedder,
    EmbeddingsUnavailable,
)
from heimdall.rag.ingest import ingest_knowledge
from heimdall.rag.store import PgVectorStore, VectorStore
from heimdall.settings import Settings
from heimdall.tools.docker import DockerClient
from heimdall.tools.loki import LokiClient
from heimdall.tools.victoriametrics import VictoriaMetricsClient

CHAT_UNAVAILABLE = "модель недоступна"
EMBEDDINGS_UNAVAILABLE = "эмбеддинги недоступны"
INGESTED = "Проиндексировано фрагментов"
STORE_UNAVAILABLE = (
    "база знаний недоступна, проверьте postgres и выполните heimdall ingest"
)
RUN_FAILED = "не удалось выполнить проверку"
INGEST_FAILED = "не удалось проиндексировать базу знаний"
BROKEN_PROPOSAL = "агент предложил действие, которое не удалось разобрать"
STILL_INTERRUPTED = "агент снова ждёт подтверждения, отчёт не готов"
RESTART_ALREADY_RAN = "Рестарт уже выполнен"
RESTART_OK = "успешно"
RESTART_FAILED = "с ошибкой"  # noqa: RUF001
_UNIX_PREFIX = "unix://"


@dataclass(frozen=True)
class AppDeps:
    store: VectorStore
    embedder: Embedder
    chat: ChatModel
    docker: DockerClient
    loki: LokiClient
    vm: VictoriaMetricsClient
    channel: UserChannel
    checkpointer: BaseCheckpointSaver[Any]
    knowledge_dir: Path


def main(argv: list[str] | None = None, deps: AppDeps | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if args.command == "ask":
        return asyncio.run(_ask(args.question, deps))
    return asyncio.run(_ingest(deps))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heimdall",
        description="DevOps agent for a homelab",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="diagnose a problem in the homelab")
    ask.add_argument("question", help="question in free form")
    commands.add_parser("ingest", help="index the knowledge base")
    return parser


async def _ask(question: str, deps: AppDeps | None) -> int:
    if deps is not None:
        return await _run_ask(question, deps)
    async with _production_deps() as production:
        return await _run_ask(question, production)


async def _ingest(deps: AppDeps | None) -> int:
    if deps is not None:
        return await _run_ingest(deps)
    async with _production_deps() as production:
        return await _run_ingest(production)


async def _run_ask(question: str, deps: AppDeps) -> int:
    graph = build_graph(
        retriever=deps.store,
        embedder=deps.embedder,
        chat=deps.chat,
        docker=deps.docker,
        loki=deps.loki,
        vm=deps.vm,
        checkpointer=deps.checkpointer,
    )
    thread = {"thread_id": str(uuid4())}
    try:
        state = dict(
            await graph.ainvoke(_initial_state(question), {"configurable": thread})
        )
        if _is_interrupted(state):
            action = _pending_action(state)
            if action is None:
                deps.channel.emit(BROKEN_PROPOSAL)
                return 1
            decision = "yes" if deps.channel.confirm(action) else "no"
            state = dict(
                await graph.ainvoke(Command(resume=decision), {"configurable": thread})
            )
            if _is_interrupted(state):
                deps.channel.emit(STILL_INTERRUPTED)
                return 1
    except ChatUnavailable:
        return await _fail(graph, thread, deps.channel, CHAT_UNAVAILABLE)
    except asyncpg.PostgresError as exc:
        return await _fail(graph, thread, deps.channel, f"{STORE_UNAVAILABLE}: {exc}")
    except Exception as exc:
        return await _fail(graph, thread, deps.channel, f"{RUN_FAILED}: {exc}")
    deps.channel.emit(_report(state))
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
        deps.channel.emit(EMBEDDINGS_UNAVAILABLE)
        return 1
    except Exception as exc:
        deps.channel.emit(f"{INGEST_FAILED}: {exc}")
        return 1
    deps.channel.emit(f"{INGESTED}: {count}")
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


def _is_interrupted(state: dict[str, Any]) -> bool:
    return bool(state.get("__interrupt__"))


def _pending_action(state: dict[str, Any]) -> Action | None:
    interrupts = state.get("__interrupt__")
    if not isinstance(interrupts, list | tuple) or not interrupts:
        return None
    value = getattr(interrupts[0], "value", None)
    if not isinstance(value, dict):
        return None
    proposed = value.get("proposed_action")
    if not isinstance(proposed, dict):
        return None
    return Action(
        tool=_text(proposed.get("tool")) or "restart",
        target=_text(proposed.get("target")),
        reason=_text(proposed.get("reason")),
        risk=_text(proposed.get("risk")),
    )


def _report(state: dict[str, Any]) -> str:
    report = state.get("report")
    if isinstance(report, str) and report:
        return report
    return EMPTY_REPORT


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def _docker_connector(docker_host: str) -> aiohttp.BaseConnector:
    if docker_host.startswith(_UNIX_PREFIX):
        return aiohttp.UnixConnector(path=docker_host.removeprefix(_UNIX_PREFIX))
    return aiohttp.TCPConnector()


@asynccontextmanager
async def _production_deps() -> AsyncIterator[AppDeps]:
    settings = Settings()  # type: ignore[call-arg]
    async with (
        aiohttp.ClientSession() as http,
        aiohttp.ClientSession(
            connector=_docker_connector(settings.docker_host)
        ) as docker_http,
        AsyncSqliteSaver.from_conn_string(settings.checkpoint_path) as checkpointer,
    ):
        yield AppDeps(
            store=PgVectorStore(settings.postgres_dsn),
            embedder=GigaChatEmbedder(settings, http),
            chat=GigaChatChatModel(settings, http),
            docker=DockerClient(settings.docker_host, docker_http),
            loki=LokiClient(settings.loki_url, http),
            vm=VictoriaMetricsClient(settings.victoriametrics_url, http),
            channel=CliChannel(),
            checkpointer=checkpointer,
            knowledge_dir=settings.knowledge_dir,
        )
