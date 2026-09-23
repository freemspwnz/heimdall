import asyncio
import itertools
import json
from typing import Any

import httpx
import pytest
from heimdall.api.app import create_app
from heimdall.graph import build_graph
from heimdall.models import Observation, ToolCall
from heimdall.providers import FakeChatModel, FakeEmbedder, ScriptedTurn
from heimdall.rag import InMemoryVectorStore
from heimdall.runtime.runner import AskRunner
from httpx import ASGITransport
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


def graph_with_restart(docker: FakeDocker) -> Any:
    return _build(postgres_chat(), docker=docker)


@pytest.mark.asyncio
async def test_health() -> None:
    app = create_app(AskRunner(graph_without_proposal()))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ask_sse_report() -> None:
    app = create_app(AskRunner(graph_without_proposal()))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/v1/ask", json={"question": "ping"}) as resp:
            assert resp.status_code == 200
            body = "".join([chunk async for chunk in resp.aiter_text()])
    assert "event: report" in body


@pytest.mark.asyncio
async def test_ask_hitl_then_resume_yes() -> None:
    """Resume must run concurrently: httpx ASGITransport buffers the SSE body
    until the ask ASGI call finishes, so POST-from-inside-aiter_lines deadlocks.
    """
    docker = FakeDocker()
    runner = AskRunner(graph_with_restart(docker))
    app = create_app(runner)

    async def resume_when_waiting() -> None:
        for _ in range(200):
            waiting = runner._waiting
            if waiting:
                run_id = next(iter(waiting))
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    r = await client.post(
                        f"/v1/runs/{run_id}/resume",
                        json={"decision": "yes"},
                    )
                assert r.status_code == 204
                return
            await asyncio.sleep(0.01)
        msg = "run never entered HITL wait"
        raise AssertionError(msg)

    resume_task = asyncio.create_task(resume_when_waiting())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST", "/v1/ask", json={"question": POSTGRES_QUESTION}
        ) as resp:
            assert resp.status_code == 200
            body = "".join([chunk async for chunk in resp.aiter_text()])
    await resume_task
    assert "event: hitl" in body
    assert "event: report" in body
    assert docker.restart_calls == ["postgres"]


@pytest.mark.asyncio
async def test_resume_unknown_run_returns_404() -> None:
    app = create_app(AskRunner(graph_without_proposal()))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/runs/missing/resume",
            json={"decision": "no"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ask_disconnect_cancels_hitl() -> None:
    docker = FakeDocker()
    runner = AskRunner(graph_with_restart(docker))
    app = create_app(runner)

    async def do_ask() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            async with client.stream(
                "POST", "/v1/ask", json={"question": POSTGRES_QUESTION}
            ) as resp:
                async for _chunk in resp.aiter_text():
                    pass

    ask_task = asyncio.create_task(do_ask())
    for _ in range(200):
        if runner._waiting:
            break
        await asyncio.sleep(0.01)
    assert runner._waiting, "expected HITL wait before cancel"
    ask_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ask_task
    for _ in range(200):
        if not runner._lock.locked() and not runner._waiting:
            break
        await asyncio.sleep(0.01)
    assert not runner._lock.locked()
    assert docker.restart_calls == []
