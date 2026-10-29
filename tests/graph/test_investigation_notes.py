import pytest
from heimdall.application.models import ToolCall
from heimdall.infrastructure.graph.edges import after_diagnose
from heimdall.infrastructure.graph.nodes.investigate import investigate
from heimdall.infrastructure.graph.nodes.utils import _context
from heimdall.infrastructure.graph.state import GraphState
from heimdall.infrastructure.graph.tools import Tools
from heimdall.infrastructure.llms import FakeChatModel, ScriptedTurn
from tests.graph.test_graph import FakeDocker, FakeLoki, FakeVictoriaMetrics
from tests.support import SilentLogger


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


def _tools() -> Tools:
    return Tools(FakeDocker(), FakeLoki(), FakeVictoriaMetrics(), SilentLogger())


@pytest.mark.asyncio
async def test_investigate_saves_final_text_without_tools() -> None:
    chat = FakeChatModel([ScriptedTurn(content="Вижу сервисы в метриках и логах.")])
    node = investigate(chat, _tools())
    update = await node(_base_state())
    assert update["investigation_notes"] == "Вижу сервисы в метриках и логах."
    assert update["investigate_gained_observations"] is False
    assert update["investigate_rounds"] == 1
    assert update["observations"] == []


@pytest.mark.asyncio
async def test_investigate_marks_gained_when_tool_adds_observation() -> None:
    call = ToolCall(id="c1", name="docker_ps", arguments={})
    chat = FakeChatModel(
        [
            ScriptedTurn(tool_calls=[call]),
            ScriptedTurn(content="Список контейнеров снят."),
        ]
    )
    node = investigate(chat, _tools())
    update = await node(_base_state())
    assert update["investigate_gained_observations"] is True
    assert update["investigation_notes"] == "Список контейнеров снят."
    assert len(update["observations"]) == 1  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_investigate_appends_notes_across_rounds() -> None:
    chat = FakeChatModel([ScriptedTurn(content="Второй проход.")])
    node = investigate(chat, _tools())
    update = await node(
        _base_state(investigation_notes="Первый проход.", investigate_rounds=1)
    )
    assert update["investigation_notes"] == "Первый проход.\n\nВторой проход."  # noqa: RUF001


@pytest.mark.asyncio
async def test_investigate_keeps_notes_when_final_content_empty() -> None:
    chat = FakeChatModel([ScriptedTurn(content="")])
    node = investigate(chat, _tools())
    update = await node(_base_state(investigation_notes="Уже было."))
    assert update["investigation_notes"] == "Уже было."
    assert update["investigate_gained_observations"] is False


def test_context_includes_investigation_notes() -> None:
    text = _context(_base_state(investigation_notes="Краткий итог без tools."))
    assert "Заметки расследования:" in text
    assert "Краткий итог без tools." in text


def test_context_omits_notes_section_when_empty() -> None:
    text = _context(_base_state(investigation_notes=None))
    assert "Заметки расследования:" not in text


def test_after_diagnose_skips_retry_when_notes_without_new_facts() -> None:
    route = after_diagnose(
        _base_state(
            confidence=0.1,
            investigate_rounds=1,
            investigation_notes="Вижу сервисы без docker.",
            investigate_gained_observations=False,
        )
    )
    assert route == "propose"


def test_after_diagnose_retries_when_gained_observations() -> None:
    route = after_diagnose(
        _base_state(
            confidence=0.1,
            investigate_rounds=1,
            investigation_notes="Частичные факты.",
            investigate_gained_observations=True,
        )
    )
    assert route == "investigate"


def test_after_diagnose_retries_when_notes_empty_and_no_gain() -> None:
    route = after_diagnose(
        _base_state(
            confidence=0.1,
            investigate_rounds=1,
            investigation_notes=None,
            investigate_gained_observations=False,
        )
    )
    assert route == "investigate"
