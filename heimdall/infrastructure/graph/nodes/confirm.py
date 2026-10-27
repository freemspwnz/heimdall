from langgraph.types import interrupt

from ..prompts import NO_ACTION_NOTE
from ..state import GraphState, StateUpdate
from .utils import _append, _final_report, _text

POSITIVE_ANSWERS = frozenset({"y", "yes"})


def _decision(answer: object) -> str:
    if isinstance(answer, str) and answer.strip().lower() in POSITIVE_ANSWERS:
        return "yes"
    return "no"


async def confirm(state: GraphState) -> StateUpdate:
    answer = interrupt({"proposed_action": state.get("proposed_action")})
    if _decision(answer) == "yes":
        return {"human_decision": "yes"}
    report = _append(_text(state.get("report")), NO_ACTION_NOTE)
    return {"human_decision": "no", "report": _final_report(state, report)}
