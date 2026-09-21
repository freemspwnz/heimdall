import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

from heimdall.cli import AppDeps, main
from heimdall.models import (
    Action,
    ChatMessage,
    ChatResult,
    Observation,
    ToolCall,
    ToolSpec,
)
from heimdall.providers.fake import FakeChatModel, FakeEmbedder, ScriptedTurn
from heimdall.providers.protocols import ChatUnavailable, EmbeddingsUnavailable
from heimdall.rag.store import InMemoryVectorStore
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
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingsUnavailable("503 embeddings down")


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


def test_main_without_a_command_fails() -> None:
    assert main([], deps=make_deps(chat=postgres_chat())) != 0


def test_main_with_an_unknown_command_fails() -> None:
    assert main(["deploy"], deps=make_deps(chat=postgres_chat())) != 0


def test_ask_without_a_question_fails() -> None:
    assert main(["ask"], deps=make_deps(chat=postgres_chat())) != 0
