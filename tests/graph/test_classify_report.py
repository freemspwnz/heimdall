import json

import pytest
from heimdall.application.models import ChatMessage, ChatResult, ToolSpec
from heimdall.infrastructure.constants import DEFAULT_QUESTION_KIND
from heimdall.infrastructure.graph.nodes.classify import classify
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
    return ScriptedTurn(
        content=json.dumps({"question_kind": kind}, ensure_ascii=False)
    )


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
    node = classify(_RaisingChat(), SilentLogger())  # type: ignore[arg-type]
    update = await node(_base_state())
    assert update == {"question_kind": DEFAULT_QUESTION_KIND}
