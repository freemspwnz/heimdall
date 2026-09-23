import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from heimdall.graph import build_graph
from heimdall.models import (
    Action,
    Observation,
    ToolCall,
)
from heimdall.providers import FakeChatModel, FakeEmbedder, ScriptedTurn
from heimdall.rag import InMemoryVectorStore
from heimdall.runtime.events import RunEvent
from heimdall.runtime.runner import AskRunner
from langgraph.checkpoint.memory import MemorySaver

POSTGRES_QUESTION = "Что с postgres?"  # noqa: RUF001

_ids = itertools.count()


class FakeDocker:
    def __init__(self) -> None:
        self.restart_calls: list[str] = []

    async def ps(self) -> Observation:
        return Observation(source="docker", ok=True, payload="postgres running")

    async def inspect(self, name: str) -> Observation:
        return Observation(source="docker", ok=True, payload='{"State": {}}')

    async def logs(self, name: str, tail: int = 100) -> Observation:
        return Observation(source="docker", ok=True, payload="FATAL: too many clients")

    async def restart(self, name: str) -> Observation:
        self.restart_calls.append(name)
        return Observation(source="docker", ok=True, payload="")


class FakeLoki:
    async def query(self, logql: str, since: str = "15m") -> Observation:
        return Observation(source="loki", ok=True, payload="FATAL: too many clients")


class FakeVictoriaMetrics:
    async def query(self, metricsql: str) -> Observation:
        return Observation(source="victoriametrics", ok=True, payload="pg_up = 0")


def tool_call(tool: str, **arguments: object) -> ToolCall:
    return ToolCall(id=f"call-{next(_ids)}", name=tool, arguments=dict(arguments))


def diagnose_turn() -> ScriptedTurn:
    return ScriptedTurn(
        content=json.dumps(
            {
                "hypothesis": "Контейнер нездоров.",
                "confidence": 0.9,
                "unknown": "",
                "report": "Postgres рвёт соединения.",
            },
            ensure_ascii=False,
        )
    )


def propose_turn(target: str | None) -> ScriptedTurn:
    action = (
        None
        if target is None
        else {
            "tool": "restart",
            "target": target,
            "reason": "контейнер нездоров",
            "risk": "рестарт рвёт активные соединения",
        }
    )
    return ScriptedTurn(
        content=json.dumps(
            {"action": action, "report": "Нужен рестарт."}, ensure_ascii=False
        )
    )


def postgres_chat(target: str | None = "postgres") -> FakeChatModel:
    return FakeChatModel(
        [
            ScriptedTurn(tool_calls=[tool_call("docker_inspect", name="postgres")]),
            ScriptedTurn(content="Факты собраны."),
            diagnose_turn(),
            propose_turn(target),
            ScriptedTurn(content="Было: unhealthy. Сделали: рестарт. Стало: healthy."),
        ]
    )


def _build(chat: Any, docker: FakeDocker | None = None) -> Any:
    return build_graph(
        retriever=InMemoryVectorStore(),
        embedder=FakeEmbedder(),
        chat=chat,
        docker=docker if docker is not None else FakeDocker(),  # type: ignore[arg-type]
        loki=FakeLoki(),  # type: ignore[arg-type]
        vm=FakeVictoriaMetrics(),  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
    )


def graph_without_proposal() -> Any:
    chat = FakeChatModel(
        [
            ScriptedTurn(content="Факты собраны."),
            diagnose_turn(),
            propose_turn(None),
        ]
    )
    return _build(chat)


def graph_that_waits_on_hitl() -> Any:
    return _build(postgres_chat())


def graph_with_restart(docker: FakeDocker) -> Any:
    return _build(postgres_chat(), docker=docker)


async def _next_hitl(gen: AsyncIterator[RunEvent]) -> RunEvent:
    async for event in gen:
        if event.type == "hitl":
            return event
    msg = "expected hitl event"
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_ask_yields_report_without_hitl() -> None:
    runner = AskRunner(graph_without_proposal())
    events = [e async for e in runner.ask("ping")]
    assert any(e.type == "report" and e.text for e in events)
    assert not any(e.type == "hitl" for e in events)


@pytest.mark.asyncio
async def test_second_ask_while_busy_yields_busy() -> None:
    runner = AskRunner(graph_that_waits_on_hitl())
    gen = runner.ask("first")
    first = await gen.__anext__()
    while first.type != "hitl":
        first = await gen.__anext__()
    busy = [e async for e in runner.ask("second")]
    assert busy[0].type == "busy"
    await runner.resume(first.run_id, "no")
    rest = [e async for e in gen]
    assert any(e.type == "report" for e in rest)


@pytest.mark.asyncio
async def test_cancel_hitl_resumes_no_without_restart() -> None:
    docker = FakeDocker()
    runner = AskRunner(graph_with_restart(docker))
    gen = runner.ask(POSTGRES_QUESTION)
    hitl = await _next_hitl(gen)
    assert hitl.action is not None
    assert isinstance(hitl.action, Action)
    await runner.cancel_hitl(hitl.run_id)
    rest = [e async for e in gen]
    assert docker.restart_calls == []
    assert any(e.type == "report" for e in rest)


@pytest.mark.asyncio
async def test_waiting_task_cancelled_resumes_no_without_restart() -> None:
    """Consumer/task cancel while awaiting HITL Future → treat as no."""
    docker = FakeDocker()
    runner = AskRunner(graph_with_restart(docker))
    gen = runner.ask(POSTGRES_QUESTION)
    hitl = await _next_hitl(gen)
    assert hitl.run_id is not None

    async def drain_after_hitl() -> list[RunEvent]:
        return [e async for e in gen]

    task = asyncio.create_task(drain_after_hitl())
    done, _pending = await asyncio.wait({task}, timeout=0.05)
    assert not done, "drain should block on HITL Future"

    task.cancel()
    rest = await task

    assert docker.restart_calls == []
    assert any(e.type == "report" for e in rest)
    assert not runner._lock.locked()

    # Lock released: subsequent ask is not stuck on busy forever.
    follow_up_gen = runner.ask("ping")
    first = await follow_up_gen.__anext__()
    assert first.type != "busy"
    await follow_up_gen.aclose()
