import itertools
import json
from typing import Any

import pytest
from heimdall.graph import build_graph
from heimdall.models import Chunk, Observation, ToolCall, ToolSpec
from heimdall.providers.fake import FakeChatModel, FakeEmbedder, ScriptedTurn
from heimdall.providers.protocols import EmbeddingsUnavailable
from heimdall.rag.store import InMemoryVectorStore
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

POSTGRES_QUESTION = "Что с postgres?"  # noqa: RUF001
TRAEFIK_QUESTION = "Почему не открывается сервис за traefik?"
TUNNEL_QUESTION = "Почему отвалился туннель?"
LOKI_QUESTION = "Почему в логах ничего нет?"

_ids = itertools.count()


class FakeDocker:
    def __init__(
        self,
        *,
        inspect_payload: str = '{"State": {"Health": {"Status": "unhealthy"}}}',
        logs_payload: str = "FATAL: sorry, too many clients already",
        ps_payload: str = "postgres running Up 6 days (unhealthy)",
        restart_error: str | None = None,
    ) -> None:
        self._inspect_payload = inspect_payload
        self._logs_payload = logs_payload
        self._ps_payload = ps_payload
        self._restart_error = restart_error
        self.ps_calls = 0
        self.inspect_calls: list[str] = []
        self.logs_calls: list[str] = []
        self.restart_calls: list[str] = []

    async def ps(self) -> Observation:
        self.ps_calls += 1
        return Observation(source="docker", ok=True, payload=self._ps_payload)

    async def inspect(self, name: str) -> Observation:
        self.inspect_calls.append(name)
        return Observation(source="docker", ok=True, payload=self._inspect_payload)

    async def logs(self, name: str, tail: int = 100) -> Observation:
        self.logs_calls.append(name)
        return Observation(source="docker", ok=True, payload=self._logs_payload)

    async def restart(self, name: str) -> Observation:
        self.restart_calls.append(name)
        if self._restart_error is not None:
            return Observation(
                source="docker",
                ok=False,
                payload="",
                error=self._restart_error,
            )
        return Observation(source="docker", ok=True, payload="")


class FakeLoki:
    def __init__(self, payload: str = "FATAL: sorry, too many clients already") -> None:
        self._payload = payload
        self.queries: list[str] = []

    async def query(self, logql: str, since: str = "15m") -> Observation:
        self.queries.append(logql)
        return Observation(source="loki", ok=True, payload=self._payload)


class FakeVictoriaMetrics:
    def __init__(self, payload: str = "pg_up = 0") -> None:
        self._payload = payload
        self.queries: list[str] = []

    async def query(self, metricsql: str) -> Observation:
        self.queries.append(metricsql)
        return Observation(source="victoriametrics", ok=True, payload=self._payload)


class BrokenEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingsUnavailable("503 embeddings down")


def tool_call(tool: str, **arguments: object) -> ToolCall:
    return ToolCall(id=f"call-{next(_ids)}", name=tool, arguments=dict(arguments))


def text_turn(content: str) -> ScriptedTurn:
    return ScriptedTurn(content=content)


def investigate_turns(*calls: ToolCall) -> list[ScriptedTurn]:
    return [ScriptedTurn(tool_calls=list(calls)), text_turn("Факты собраны.")]


def diagnose_turn(
    confidence: object,
    *,
    fenced: bool = False,
    report: str = "Контейнер нездоров.",
) -> ScriptedTurn:
    payload = json.dumps(
        {
            "hypothesis": "Контейнер нездоров и рвёт соединения.",
            "confidence": confidence,
            "unknown": "метрики exporter недоступны",
            "report": report,
        },
        ensure_ascii=False,
    )
    if fenced:
        payload = f"```json\n{payload}\n```"
    return text_turn(payload)


def propose_turn(target: str | None, *, report: str = "Нужен рестарт.") -> ScriptedTurn:
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
    return text_turn(
        json.dumps({"action": action, "report": report}, ensure_ascii=False)
    )


async def make_graph(
    chat: FakeChatModel,
    *,
    docker: FakeDocker,
    loki: FakeLoki,
    vm: FakeVictoriaMetrics,
    embedder: Any | None = None,
) -> Any:
    store = InMemoryVectorStore()
    await store.upsert(
        [
            Chunk(
                text="Рестарт postgres рвёт активные соединения.",
                source="runbooks/postgres.md",
            ),
            Chunk(
                text="Туннель локально это sing-box и 3x-ui.",
                source="runbooks/tunnel.md",
            ),
        ],
        FakeEmbedder(),
    )
    return build_graph(
        retriever=store,
        embedder=embedder if embedder is not None else FakeEmbedder(),
        chat=chat,
        docker=docker,
        loki=loki,
        vm=vm,
        checkpointer=MemorySaver(),
    )


def config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def run_until_interrupt(
    graph: Any,
    payload: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    state = await graph.ainvoke(payload, config)
    interrupts = state.get("__interrupt__") or []
    assert interrupts, "graph finished without asking the human"
    value = interrupts[0].value
    assert isinstance(value, dict)
    return value


def tool_names(chat: FakeChatModel) -> list[list[str]]:
    names: list[list[str]] = []
    for call in chat.calls:
        specs = call["tools"]
        if specs is None:
            names.append([])
            continue
        assert isinstance(specs, list)
        names.append([spec.name for spec in specs if isinstance(spec, ToolSpec)])
    return names


def postgres_chat() -> FakeChatModel:
    return FakeChatModel(
        [
            *investigate_turns(
                tool_call("docker_inspect", name="postgres"),
                tool_call("loki_query", query='{container="postgres"}'),
                tool_call("vm_query", query="pg_up"),
            ),
            diagnose_turn(0.9, fenced=True),
            propose_turn("postgres"),
            text_turn("Было: unhealthy. Сделали: рестарт. Стало: healthy."),
        ]
    )


@pytest.mark.asyncio
async def test_postgres_confirmed_restart_executes_once_and_verifies() -> None:
    docker = FakeDocker()
    loki = FakeLoki()
    vm = FakeVictoriaMetrics()
    chat = postgres_chat()
    graph = await make_graph(chat, docker=docker, loki=loki, vm=vm)
    cfg = config("postgres-yes")

    payload = await run_until_interrupt(graph, {"question": POSTGRES_QUESTION}, cfg)
    assert payload["proposed_action"]["target"] == "postgres"

    final = await graph.ainvoke(Command(resume="yes"), cfg)

    assert docker.restart_calls == ["postgres"]
    assert final["human_decision"] == "yes"
    assert final["execution_result"]["ok"] is True
    assert docker.logs_calls == ["postgres"]
    assert final["retrieved_chunks"]
    assert final["confidence"] == 0.9
    assert final["hypothesis"]
    assert final["report"]


@pytest.mark.asyncio
async def test_postgres_rejected_restart_is_never_executed() -> None:
    docker = FakeDocker()
    chat = postgres_chat()
    graph = await make_graph(
        chat,
        docker=docker,
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )
    cfg = config("postgres-no")

    await run_until_interrupt(graph, {"question": POSTGRES_QUESTION}, cfg)
    final = await graph.ainvoke(Command(resume="no"), cfg)

    assert docker.restart_calls == []
    assert final["human_decision"] == "no"
    assert "не применял" in final["report"].lower()


@pytest.mark.asyncio
async def test_resuming_after_confirmation_does_not_repeat_the_proposal() -> None:
    chat = postgres_chat()
    graph = await make_graph(
        chat,
        docker=FakeDocker(),
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )
    cfg = config("no-double-propose")

    payload = await run_until_interrupt(graph, {"question": POSTGRES_QUESTION}, cfg)
    calls_before_resume = len(chat.calls)

    final = await graph.ainvoke(Command(resume="yes"), cfg)

    assert len(chat.calls) == calls_before_resume + 1
    assert final["proposed_action"] == payload["proposed_action"]


@pytest.mark.asyncio
async def test_verify_sees_that_the_restart_failed() -> None:
    docker = FakeDocker(restart_error="500 container is in a broken state")
    chat = postgres_chat()
    graph = await make_graph(
        chat,
        docker=docker,
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )
    cfg = config("restart-failed")

    await run_until_interrupt(graph, {"question": POSTGRES_QUESTION}, cfg)
    final = await graph.ainvoke(Command(resume="yes"), cfg)

    assert final["execution_result"]["ok"] is False
    verify_messages = chat.calls[-1]["messages"]
    assert isinstance(verify_messages, list)
    assert "container is in a broken state" in verify_messages[-1].content


@pytest.mark.asyncio
async def test_empty_loki_finishes_with_coverage_note() -> None:
    loki = FakeLoki("no streams")
    chat = FakeChatModel(
        [
            *investigate_turns(tool_call("loki_query", query='{container="jellyfin"}')),
            diagnose_turn(0.8),
            propose_turn(None, report="Логов за окно нет."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=FakeDocker(),
        loki=loki,
        vm=FakeVictoriaMetrics(),
    )

    final = await graph.ainvoke({"question": LOKI_QUESTION}, config("loki-empty"))

    assert final["proposed_action"] is None
    report = final["report"].lower()
    assert "покрытие" in report or "пуст" in report


@pytest.mark.asyncio
async def test_low_confidence_investigates_exactly_twice() -> None:
    docker = FakeDocker()
    chat = FakeChatModel(
        [
            *investigate_turns(tool_call("docker_ps")),
            diagnose_turn(0.1),
            *investigate_turns(tool_call("docker_ps")),
            diagnose_turn(0.1),
            propose_turn(None, report="Нужна ручная проверка."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=docker,
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )

    final = await graph.ainvoke({"question": POSTGRES_QUESTION}, config("two-rounds"))

    assert final["investigate_rounds"] == 2
    assert docker.ps_calls == 2
    assert final["confidence"] == 0.1
    assert final["proposed_action"] is None


@pytest.mark.asyncio
async def test_investigate_never_offers_the_restart_tool() -> None:
    chat = postgres_chat()
    graph = await make_graph(
        chat,
        docker=FakeDocker(),
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )
    cfg = config("tools-audit")

    await run_until_interrupt(graph, {"question": POSTGRES_QUESTION}, cfg)
    await graph.ainvoke(Command(resume="yes"), cfg)

    offered = tool_names(chat)
    assert all("docker_restart" not in names for names in offered)
    assert any("docker_inspect" in names for names in offered)
    assert any("loki_query" in names for names in offered)


@pytest.mark.asyncio
async def test_investigate_history_keeps_assistant_tool_calls_before_results() -> None:
    inspect = tool_call("docker_inspect", name="postgres")
    chat = FakeChatModel(
        [
            ScriptedTurn(tool_calls=[inspect]),
            text_turn("Факты собраны."),
            diagnose_turn(0.8),
            propose_turn(None, report="Нужна ручная проверка."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=FakeDocker(),
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )

    await graph.ainvoke({"question": POSTGRES_QUESTION}, config("tool-call-history"))

    second_round = chat.calls[1]["messages"]
    assert isinstance(second_round, list)
    roles = [message.role for message in second_round]
    assistant_index = roles.index("assistant")
    tool_index = roles.index("tool")
    assert assistant_index < tool_index
    assert second_round[assistant_index].tool_calls == [inspect]
    assert second_round[tool_index].tool_call_id == inspect.id
    assert second_round[tool_index].name == "docker_inspect"


@pytest.mark.asyncio
async def test_tunnel_report_states_remote_vpn_was_not_inspected() -> None:
    docker = FakeDocker()
    chat = FakeChatModel(
        [
            *investigate_turns(
                tool_call("docker_inspect", name="sing-box"),
                tool_call("docker_logs", name="3x-ui"),
            ),
            diagnose_turn(0.8, report="sing-box не поднял соединение."),
            propose_turn("sing-box"),
            text_turn(
                "Было: соединения нет. Сделали: рестарт. Стало: туннель поднялся."
            ),
        ]
    )
    graph = await make_graph(
        chat,
        docker=docker,
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )
    cfg = config("tunnel-yes")

    await run_until_interrupt(graph, {"question": TUNNEL_QUESTION}, cfg)
    final = await graph.ainvoke(Command(resume="yes"), cfg)

    assert docker.restart_calls == ["sing-box"]
    assert "удалённ" in final["report"].lower()


@pytest.mark.asyncio
async def test_traefik_proposal_outside_allowlist_is_dropped() -> None:
    docker = FakeDocker()
    chat = FakeChatModel(
        [
            *investigate_turns(tool_call("docker_logs", name="traefik")),
            diagnose_turn(0.8),
            propose_turn("vaultwarden", report="Бэкенд отдаёт 502."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=docker,
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )

    final = await graph.ainvoke({"question": TRAEFIK_QUESTION}, config("traefik-deny"))

    assert final["proposed_action"] is None
    assert docker.restart_calls == []
    assert "502" in final["report"]


@pytest.mark.asyncio
async def test_traefik_backend_restart_is_proposed_for_whoami() -> None:
    docker = FakeDocker()
    chat = FakeChatModel(
        [
            *investigate_turns(tool_call("docker_logs", name="traefik")),
            diagnose_turn(0.8),
            propose_turn("whoami"),
            text_turn("Было: 502. Сделали: рестарт whoami. Стало: 200."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=docker,
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )
    cfg = config("traefik-allow")

    payload = await run_until_interrupt(graph, {"question": TRAEFIK_QUESTION}, cfg)
    assert payload["proposed_action"]["target"] == "whoami"

    final = await graph.ainvoke(Command(resume="yes"), cfg)

    assert docker.restart_calls == ["whoami"]
    assert final["report"]


@pytest.mark.asyncio
async def test_graph_investigates_when_embeddings_are_unavailable() -> None:
    chat = FakeChatModel(
        [
            *investigate_turns(
                tool_call("docker_inspect", name="postgres"),
                tool_call("loki_query", query='{container="postgres"}'),
            ),
            diagnose_turn(0.8),
            propose_turn(None, report="Диагноз без runbook."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=FakeDocker(),
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
        embedder=BrokenEmbedder(),
    )

    final = await graph.ainvoke(
        {"question": POSTGRES_QUESTION}, config("no-embeddings")
    )

    assert final["retrieved_chunks"] == []
    assert len(final["observations"]) == 2
    assert final["report"]


@pytest.mark.asyncio
async def test_invalid_confidence_falls_back_to_default() -> None:
    chat = FakeChatModel(
        [
            *investigate_turns(tool_call("docker_ps")),
            diagnose_turn("не знаю"),
            propose_turn(None, report="Нужна ручная проверка."),
        ]
    )
    graph = await make_graph(
        chat,
        docker=FakeDocker(),
        loki=FakeLoki(),
        vm=FakeVictoriaMetrics(),
    )

    final = await graph.ainvoke(
        {"question": POSTGRES_QUESTION}, config("bad-confidence")
    )

    assert final["confidence"] == 0.7
    assert final["investigate_rounds"] == 1
