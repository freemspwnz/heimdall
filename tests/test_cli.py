import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from heimdall.cli import AppDeps, main
from heimdall.models import (
    Action,
    ChatMessage,
    ChatResult,
    Chunk,
    Observation,
    ToolCall,
    ToolSpec,
)
from heimdall.providers import (
    ChatUnavailable,
    Embedder,
    EmbeddingsUnavailable,
    FakeChatModel,
    FakeEmbedder,
    ScriptedTurn,
)
from heimdall.rag import InMemoryVectorStore
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


class FakeChannel:
    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.messages: list[str] = []
        self.actions: list[Action] = []

    def emit(self, text: str) -> None:
        self.messages.append(text)

    def confirm(self, action: Action) -> bool:
        self.actions.append(action)
        return self.answer

    @property
    def output(self) -> str:
        return "\n".join(self.messages)


class FlakyChatModel:
    def __init__(self, inner: FakeChatModel, fail_after: int) -> None:
        self._inner = inner
        self._fail_after = fail_after
        self.calls = 0

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        if self.calls >= self._fail_after:
            raise ChatUnavailable("503 model is down")
        self.calls += 1
        return await self._inner.complete(messages, tools)


class BrokenEmbedder:
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del texts, query
        raise EmbeddingsUnavailable("503 embeddings down")


class BrokenStore:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None:
        raise self._error

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = 5,
    ) -> list[Chunk]:
        raise self._error


class StubInterrupt:
    def __init__(self, value: object) -> None:
        self.value = value


class StubGraph:
    def __init__(self, value: object) -> None:
        self._value = value
        self.invocations = 0

    async def ainvoke(self, payload: object, config: object) -> dict[str, object]:
        self.invocations += 1
        return {
            "report": "черновик",
            "__interrupt__": [StubInterrupt(self._value)],
        }

    async def aget_state(self, config: object) -> object:
        return None


def patch_graph(monkeypatch: pytest.MonkeyPatch, graph: StubGraph) -> None:
    monkeypatch.setattr("heimdall.cli.build_graph", lambda **kwargs: graph)


class ExplodingDeps:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aenter__(self) -> AppDeps:
        raise self._error

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def patch_production_deps(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr("heimdall.cli._production_deps", lambda: ExplodingDeps(error))


def patch_ingest_production_deps(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(
        "heimdall.cli._ingest_production_deps", lambda: ExplodingDeps(error)
    )


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


def make_deps(
    *,
    chat: Any,
    docker: FakeDocker | None = None,
    channel: FakeChannel | None = None,
    store: Any | None = None,
    embedder: Any | None = None,
    knowledge_dir: Path = Path("docs/knowledge"),
) -> AppDeps:
    return AppDeps(
        store=store if store is not None else InMemoryVectorStore(),
        embedder=embedder if embedder is not None else FakeEmbedder(),
        chat=chat,
        docker=docker if docker is not None else FakeDocker(),  # type: ignore[arg-type]
        loki=FakeLoki(),  # type: ignore[arg-type]
        vm=FakeVictoriaMetrics(),  # type: ignore[arg-type]
        channel=channel if channel is not None else FakeChannel(),
        checkpointer=MemorySaver(),
        knowledge_dir=knowledge_dir,
    )


def write_knowledge(root: Path) -> Path:
    knowledge = root / "knowledge"
    (knowledge / "runbooks").mkdir(parents=True)
    (knowledge / "inventory.md").write_text(
        "## Хост\nОдин docker-хост.\n",  # noqa: RUF001
        encoding="utf-8",
    )
    (knowledge / "runbooks" / "postgres.md").write_text(
        "## Postgres\nРестарт рвёт активные соединения.\n",  # noqa: RUF001
        encoding="utf-8",
    )
    return knowledge


def test_ask_executes_the_restart_when_the_human_confirms() -> None:
    docker = FakeDocker()
    channel = FakeChannel(answer=True)
    deps = make_deps(chat=postgres_chat(), docker=docker, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code == 0
    assert docker.restart_calls == ["postgres"]
    assert channel.output


def test_ask_never_restarts_when_the_human_declines() -> None:
    docker = FakeDocker()
    channel = FakeChannel(answer=False)
    deps = make_deps(chat=postgres_chat(), docker=docker, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code == 0
    assert docker.restart_calls == []


def test_ask_shows_the_proposed_action_to_the_channel() -> None:
    channel = FakeChannel(answer=False)
    deps = make_deps(chat=postgres_chat(), channel=channel)

    main(["ask", POSTGRES_QUESTION], deps=deps)

    assert len(channel.actions) == 1
    action = channel.actions[0]
    assert action.tool == "restart"
    assert action.target == "postgres"
    assert action.reason == "контейнер нездоров"
    assert action.risk == "рестарт рвёт активные соединения"


def test_ask_emits_the_final_report() -> None:
    channel = FakeChannel(answer=True)
    deps = make_deps(chat=postgres_chat(), channel=channel)

    main(["ask", POSTGRES_QUESTION], deps=deps)

    assert "Стало: healthy." in channel.output


def test_ask_without_a_proposal_does_not_ask_the_human() -> None:
    channel = FakeChannel(answer=True)
    docker = FakeDocker()
    deps = make_deps(chat=postgres_chat(None), docker=docker, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code == 0
    assert channel.actions == []
    assert docker.restart_calls == []
    assert "Нужен рестарт." in channel.output


def test_ask_reports_that_the_model_is_unavailable() -> None:
    docker = FakeDocker()
    channel = FakeChannel(answer=True)
    chat = FlakyChatModel(postgres_chat(), fail_after=0)
    deps = make_deps(chat=chat, docker=docker, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code == 1
    assert "модель недоступна" in channel.output
    assert docker.restart_calls == []


def test_ask_reports_model_failure_after_the_resume() -> None:
    channel = FakeChannel(answer=True)
    chat = FlakyChatModel(postgres_chat(), fail_after=4)
    deps = make_deps(chat=chat, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code == 1
    assert "модель недоступна" in channel.output


def test_ask_says_the_restart_already_ran_when_verify_loses_the_model() -> None:
    docker = FakeDocker()
    channel = FakeChannel(answer=True)
    chat = FlakyChatModel(postgres_chat(), fail_after=4)
    deps = make_deps(chat=chat, docker=docker, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code == 1
    assert docker.restart_calls == ["postgres"]
    output = channel.output.lower()
    assert "рестарт" in output
    assert "postgres" in output


def test_ask_does_not_mention_a_restart_that_never_happened() -> None:
    channel = FakeChannel(answer=True)
    chat = FlakyChatModel(postgres_chat(), fail_after=0)
    deps = make_deps(chat=chat, channel=channel)

    main(["ask", POSTGRES_QUESTION], deps=deps)

    assert "рестарт" not in channel.output.lower()


def test_ask_points_at_ingest_when_the_knowledge_store_is_missing() -> None:
    channel = FakeChannel()
    store = BrokenStore(asyncpg.UndefinedTableError('relation "chunks" does not exist'))
    deps = make_deps(chat=postgres_chat(), store=store, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code != 0
    assert "ingest" in channel.output


def test_ask_reports_an_unexpected_infrastructure_failure() -> None:
    channel = FakeChannel()
    store = BrokenStore(ConnectionRefusedError("postgres refused the connection"))
    deps = make_deps(chat=postgres_chat(), store=store, channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code != 0
    assert "postgres refused the connection" in channel.output


def test_ask_fails_when_the_interrupt_payload_is_not_an_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(answer=True)
    graph = StubGraph({"proposed_action": None})
    patch_graph(monkeypatch, graph)
    deps = make_deps(chat=postgres_chat(), channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code != 0
    assert graph.invocations == 1
    assert channel.actions == []
    assert channel.output


def test_ask_fails_when_the_graph_is_still_interrupted_after_the_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(answer=True)
    graph = StubGraph(
        {
            "proposed_action": {
                "tool": "restart",
                "target": "postgres",
                "reason": "контейнер нездоров",
                "risk": "рестарт рвёт соединения",
            }
        }
    )
    patch_graph(monkeypatch, graph)
    deps = make_deps(chat=postgres_chat(), channel=channel)

    code = main(["ask", POSTGRES_QUESTION], deps=deps)

    assert code != 0
    assert graph.invocations == 2
    assert len(channel.actions) == 1
    assert "черновик" not in channel.output


def test_ingest_upserts_the_knowledge_directory(tmp_path: Path) -> None:
    store = InMemoryVectorStore()
    channel = FakeChannel()
    deps = make_deps(
        chat=postgres_chat(),
        channel=channel,
        store=store,
        knowledge_dir=write_knowledge(tmp_path),
    )

    code = main(["ingest"], deps=deps)

    assert code == 0
    found = asyncio.run(store.search("postgres", FakeEmbedder()))
    assert [chunk.source for chunk in found] == [
        "runbooks/postgres.md",
        "inventory.md",
    ]
    assert "2" in channel.output


def test_ingest_reports_unavailable_embeddings(tmp_path: Path) -> None:
    channel = FakeChannel()
    deps = make_deps(
        chat=postgres_chat(),
        channel=channel,
        embedder=BrokenEmbedder(),
        knowledge_dir=write_knowledge(tmp_path),
    )

    code = main(["ingest"], deps=deps)

    assert code == 1
    assert "эмбеддинги недоступны" in channel.output


def test_ingest_reports_an_unreachable_store(tmp_path: Path) -> None:
    channel = FakeChannel()
    store = BrokenStore(ConnectionRefusedError("postgres refused the connection"))
    deps = make_deps(
        chat=postgres_chat(),
        channel=channel,
        store=store,
        knowledge_dir=write_knowledge(tmp_path),
    )

    code = main(["ingest"], deps=deps)

    assert code != 0
    assert "postgres refused the connection" in channel.output


def test_ask_reports_a_broken_production_setup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    patch_production_deps(
        monkeypatch, ValueError("gigachat_credentials field required")
    )

    code = main(["ask", POSTGRES_QUESTION])

    assert code == 1
    assert "gigachat_credentials field required" in capsys.readouterr().err


def test_ingest_reports_a_broken_production_setup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    patch_ingest_production_deps(monkeypatch, OSError("unable to open database file"))

    code = main(["ingest"])

    assert code == 1
    assert "unable to open database file" in capsys.readouterr().err


def test_ingest_uses_ingest_production_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Marker:
        async def __aenter__(self) -> AppDeps:
            seen.append("ingest")
            raise RuntimeError("stop-after-wiring")

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr("heimdall.cli._ingest_production_deps", lambda: Marker())
    monkeypatch.setattr(
        "heimdall.cli._production_deps",
        lambda: (_ for _ in ()).throw(AssertionError("ask deps used for ingest")),
    )

    code = main(["ingest"])

    assert code == 1
    assert seen == ["ingest"]


def test_docker_connector_requires_unix_socket() -> None:
    from heimdall.cli import _docker_connector

    with pytest.raises(ValueError, match="unix://"):
        _docker_connector("tcp://127.0.0.1:2375")


def test_main_without_a_command_fails() -> None:
    assert main([], deps=make_deps(chat=postgres_chat())) != 0


def test_main_with_an_unknown_command_fails() -> None:
    assert main(["deploy"], deps=make_deps(chat=postgres_chat())) != 0


def test_ask_without_a_question_fails() -> None:
    assert main(["ask"], deps=make_deps(chat=postgres_chat())) != 0
