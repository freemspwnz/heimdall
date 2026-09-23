import asyncio
import itertools
import json
import socket
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import aiohttp
import pytest
import uvicorn
from heimdall.api.app import create_app
from heimdall.client.repl import AGENT_UNAVAILABLE, run_repl
from heimdall.client.session import AgentClient
from heimdall.graph import build_graph
from heimdall.models import Observation, ToolCall
from heimdall.providers import FakeChatModel, FakeEmbedder, ScriptedTurn
from heimdall.rag import InMemoryVectorStore
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


def graph_with_restart(docker: FakeDocker) -> Any:
    return _build(postgres_chat(), docker=docker)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _serve(app: Any) -> AsyncIterator[str]:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "uvicorn failed to start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
def serve_app() -> Callable[[Any], AsyncIterator[str]]:
    return _serve


@pytest.mark.asyncio
async def test_client_ask_parses_report(
    serve_app: Callable[[Any], AsyncIterator[str]],
) -> None:
    app = create_app(AskRunner(graph_without_proposal()))
    async for base_url in serve_app(app):
        async with aiohttp.ClientSession() as http:
            client = AgentClient(base_url, http=http)
            events = [e async for e in client.ask("ping")]
        assert any(e.type == "report" and e.text for e in events)
        return


@pytest.mark.asyncio
async def test_client_ask_and_resume_hitl(
    serve_app: Callable[[Any], AsyncIterator[str]],
) -> None:
    docker = FakeDocker()
    app = create_app(AskRunner(graph_with_restart(docker)))
    async for base_url in serve_app(app):
        async with aiohttp.ClientSession() as http:
            client = AgentClient(base_url, http=http)
            events = []
            async for event in client.ask(POSTGRES_QUESTION):
                events.append(event)
                if event.type == "hitl":
                    assert event.run_id is not None
                    assert event.action is not None
                    await client.resume(event.run_id, "yes")
        assert any(e.type == "hitl" for e in events)
        assert any(e.type == "report" for e in events)
        assert docker.restart_calls == ["postgres"]
        return


@pytest.mark.asyncio
async def test_repl_confirms_hitl(
    serve_app: Callable[[Any], AsyncIterator[str]],
) -> None:
    docker = FakeDocker()
    app = create_app(AskRunner(graph_with_restart(docker)))
    answers: Iterator[str] = iter([POSTGRES_QUESTION, "exit"])
    confirms: Iterator[str] = iter(["y"])
    outputs: list[str] = []

    async for base_url in serve_app(app):
        code = await run_repl(
            base_url,
            input_fn=lambda: next(answers),
            confirm_fn=lambda: next(confirms),
            output_fn=outputs.append,
        )
        assert code == 0
        assert docker.restart_calls == ["postgres"]
        joined = "\n".join(outputs)
        assert "Стало: healthy." in joined
        assert "postgres" in joined.lower()
        assert "heimdall>" not in joined
        assert "Выполнить?" not in joined
        return


@pytest.mark.asyncio
async def test_repl_unavailable_agent_returns_1() -> None:
    outputs: list[str] = []
    code = await run_repl(
        "http://127.0.0.1:1",
        input_fn=lambda: "ping",
        output_fn=outputs.append,
    )
    assert code == 1
    assert AGENT_UNAVAILABLE in "\n".join(outputs)
