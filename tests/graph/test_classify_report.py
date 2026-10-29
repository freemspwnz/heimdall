import json
from pathlib import Path

import pytest
from heimdall.application.models import ChatMessage, ChatResult, ToolSpec
from heimdall.infrastructure.constants import DEFAULT_QUESTION_KIND
from heimdall.infrastructure.graph.edges import after_investigate
from heimdall.infrastructure.graph.nodes.answer import answer
from heimdall.infrastructure.graph.nodes.classify import classify
from heimdall.infrastructure.graph.prompts import CLASSIFY_SYSTEM, COVERAGE_NOTE
from heimdall.infrastructure.graph.state import GraphState
from heimdall.infrastructure.llms import FakeChatModel, ScriptedTurn
from tests.support import RecordingLogger, SilentLogger


def _base_state(**overrides: object) -> GraphState:
    state: GraphState = {
        "question": "какие сервисы видишь?",
        "retrieved_chunks": [],
        "observations": [],
        "hypothesis": None,
        "confidence": None,
        "investigate_rounds": 0,
        "proposed_action": None,
        "human_decision": None,
        "execution_result": None,
        "report": None,
        "investigation_notes": None,
        "investigate_gained_observations": False,
        "question_kind": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _kind_turn(kind: str, runbooks: list[str] | None = None) -> ScriptedTurn:
    payload: dict[str, object] = {"question_kind": kind}
    if runbooks is not None:
        payload["runbooks"] = runbooks
    return ScriptedTurn(content=json.dumps(payload, ensure_ascii=False))


def _patch_runbooks(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        "heimdall.infrastructure.graph.paths.RUNBOOKS_DIR",
        root,
    )


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")


POSTGRES = (
    "# Postgres: база\n"
    "\n"
    "между заголовком и секцией\n"
    "\n"
    "## Когда\n"
    "что с базой?\n"  # noqa: RUF001
    "\n"
    "## Куда смотреть\n"
    "docker inspect postgres\n"
)

TUNNEL = """# Туннель

## Когда
почему отвалился туннель?
"""


class _RaisingChat:
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        *,
        node: str = "",
    ) -> ChatResult:
        del messages, tools, node
        raise RuntimeError("chat down")


@pytest.mark.asyncio
async def test_classify_writes_status() -> None:
    logger = RecordingLogger()
    node = classify(FakeChatModel([_kind_turn("status", [])]), logger)
    update = await node(_base_state())
    assert update == {"question_kind": "status", "runbooks": []}
    assert any("status" in line for line in logger.lines)


@pytest.mark.asyncio
async def test_classify_rejects_unknown_kind() -> None:
    node = classify(FakeChatModel([_kind_turn("poetry", [])]), SilentLogger())
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND, "runbooks": []}


@pytest.mark.asyncio
async def test_classify_rejects_non_json() -> None:
    node = classify(FakeChatModel([ScriptedTurn(content="не json")]), SilentLogger())
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND, "runbooks": []}


@pytest.mark.asyncio
async def test_classify_exception_defaults_to_diagnose() -> None:
    logger = RecordingLogger()
    node = classify(_RaisingChat(), logger)  # type: ignore[arg-type]
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND, "runbooks": []}
    assert any("classify failed" in line for line in logger.lines)


def test_after_investigate_routes_status_to_answer() -> None:
    assert after_investigate(_base_state(question_kind="status")) == "answer"
    assert after_investigate(_base_state(question_kind="meta")) == "answer"


def test_after_investigate_routes_action_path_to_diagnose() -> None:
    assert after_investigate(_base_state(question_kind="diagnose")) == "diagnose"
    assert after_investigate(_base_state(question_kind="action")) == "diagnose"
    assert after_investigate(_base_state(question_kind=None)) == "diagnose"
    assert after_investigate(_base_state(question_kind="poetry")) == "diagnose"


@pytest.mark.asyncio
async def test_answer_writes_report_from_notes() -> None:
    chat = FakeChatModel(
        [
            ScriptedTurn(
                content=json.dumps(
                    {"report": "В метриках видны postgres и loki."},  # noqa: RUF001
                    ensure_ascii=False,
                )
            )
        ]
    )
    node = answer(chat)
    update = await node(
        _base_state(
            investigation_notes="Вижу postgres и loki.",
            retrieved_chunks=[
                {"source": "inventory.md", "text": "сервисы: postgres, loki"}
            ],
        )
    )
    assert update.get("proposed_action") is None
    assert "proposed_action" not in update
    report = update["report"]
    assert isinstance(report, str)
    assert "postgres" in report
    assert "loki" in report


@pytest.mark.asyncio
async def test_answer_empty_report_uses_final_report_fallback() -> None:
    chat = FakeChatModel(
        [ScriptedTurn(content=json.dumps({"report": ""}, ensure_ascii=False))]
    )
    node = answer(chat)
    update = await node(
        _base_state(
            observations=[
                {
                    "source": "loki",
                    "ok": True,
                    "payload": "no streams",
                    "error": "",
                    "tool": "loki_query",
                    "target": "",
                    "since": "15m",
                    "query": '{container="x"}',
                }
            ]
        )
    )
    report = update["report"]
    assert isinstance(report, str)
    assert COVERAGE_NOTE in report


@pytest.mark.asyncio
async def test_classify_catalog_sends_name_title_and_first_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path)
    _write(tmp_path, "tunnel.md", TUNNEL)
    _write(tmp_path, "postgres.md", POSTGRES)
    (tmp_path / "skip.md").mkdir()
    chat = FakeChatModel([_kind_turn("diagnose", [])])
    await classify(chat, SilentLogger())(_base_state())
    messages = chat.calls[0]["messages"]
    assert isinstance(messages, list)
    assert messages[0].content == CLASSIFY_SYSTEM
    user = messages[1].content
    assert "Вопрос: какие сервисы видишь?" in user
    assert user.index("postgres.md") < user.index("tunnel.md")
    assert "# Postgres: база" in user
    assert "## Когда" in user
    assert "что с базой?" in user  # noqa: RUF001
    assert "между заголовком и секцией" not in user
    assert "docker inspect postgres" not in user
    assert "skip.md" not in user
    assert "бд" in CLASSIFY_SYSTEM
    assert "заголовку и секции" not in CLASSIFY_SYSTEM


@pytest.mark.asyncio
async def test_classify_skips_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path)
    _write(tmp_path, "postgres.md", POSTGRES)
    bad = tmp_path / "bad.md"
    bad.write_text("# Bad\n\n## Когда\nsecret\n", encoding="utf-8")
    bad.chmod(0)
    try:
        chat = FakeChatModel([_kind_turn("diagnose", ["postgres.md"])])
        update = await classify(chat, SilentLogger())(_base_state())
    finally:
        bad.chmod(0o644)
    user = chat.calls[0]["messages"][1].content
    assert "secret" not in user
    assert "postgres.md" in user
    assert len(chat.calls) == 1
    assert update == {"question_kind": "diagnose", "runbooks": ["postgres.md"]}


@pytest.mark.asyncio
async def test_classify_skips_invalid_utf8_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path)
    _write(tmp_path, "postgres.md", POSTGRES)
    (tmp_path / "bad.md").write_bytes(b"# Bad\n\n## When\nsecret-utf8\xff\n")
    chat = FakeChatModel([_kind_turn("diagnose", ["postgres.md"])])
    update = await classify(chat, SilentLogger())(_base_state())
    user = chat.calls[0]["messages"][1].content
    assert "secret-utf8" not in user
    assert "bad.md" not in user
    assert "postgres.md" in user
    assert len(chat.calls) == 1
    assert update == {"question_kind": "diagnose", "runbooks": ["postgres.md"]}


@pytest.mark.asyncio
async def test_classify_keeps_exact_names_and_valid_kind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path)
    _write(tmp_path, "postgres.md", POSTGRES)
    _write(tmp_path, "tunnel.md", TUNNEL)
    raw = {
        "question_kind": "status",
        "runbooks": [
            "../inventory.md",
            "postgres.md",
            "postgres.md",
            "nope.md",
            " tunnel.md ",
            1,
            "runbooks/postgres.md",
        ],
    }
    chat = FakeChatModel([ScriptedTurn(content=json.dumps(raw, ensure_ascii=False))])
    update = await classify(chat, SilentLogger())(_base_state())
    assert update == {"question_kind": "status", "runbooks": ["postgres.md"]}


@pytest.mark.asyncio
async def test_classify_invalid_kind_keeps_runbooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path)
    _write(tmp_path, "postgres.md", POSTGRES)
    chat = FakeChatModel([_kind_turn("poetry", ["postgres.md"])])
    update = await classify(chat, SilentLogger())(_base_state())
    assert update == {
        "question_kind": DEFAULT_QUESTION_KIND,
        "runbooks": ["postgres.md"],
    }


@pytest.mark.asyncio
async def test_missing_runbooks_key_forces_diagnose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path)
    _write(tmp_path, "postgres.md", POSTGRES)
    chat = FakeChatModel([_kind_turn("status")])
    update = await classify(chat, SilentLogger())(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND, "runbooks": []}


@pytest.mark.asyncio
async def test_empty_catalog_still_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_runbooks(monkeypatch, tmp_path / "missing")
    chat = FakeChatModel([_kind_turn("meta", [])])
    update = await classify(chat, SilentLogger())(_base_state())
    assert len(chat.calls) == 1
    assert update == {"question_kind": "meta", "runbooks": []}
