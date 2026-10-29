import json

import pytest
from heimdall.application.models import ChatMessage, ChatResult, ToolSpec
from heimdall.infrastructure.constants import DEFAULT_QUESTION_KIND
from heimdall.infrastructure.graph.edges import after_investigate
from heimdall.infrastructure.graph.nodes.answer import answer
from heimdall.infrastructure.graph.nodes.classify import classify
from heimdall.infrastructure.graph.prompts import COVERAGE_NOTE
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


def _kind_turn(kind: str) -> ScriptedTurn:
    return ScriptedTurn(content=json.dumps({"question_kind": kind}, ensure_ascii=False))


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
    node = classify(FakeChatModel([_kind_turn("status")]), logger)
    update = await node(_base_state())
    assert update == {"question_kind": "status"}
    assert any("status" in line for line in logger.lines)


@pytest.mark.asyncio
async def test_classify_rejects_unknown_kind() -> None:
    node = classify(FakeChatModel([_kind_turn("poetry")]), SilentLogger())
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND}


@pytest.mark.asyncio
async def test_classify_rejects_non_json() -> None:
    node = classify(FakeChatModel([ScriptedTurn(content="не json")]), SilentLogger())
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND}


@pytest.mark.asyncio
async def test_classify_exception_defaults_to_diagnose() -> None:
    logger = RecordingLogger()
    node = classify(_RaisingChat(), logger)  # type: ignore[arg-type]
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND}
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
