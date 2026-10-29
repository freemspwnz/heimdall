from ..constants import (
    CONFIDENCE_RETRY_THRESHOLD,
    DEFAULT_CONFIDENCE,
    MAX_INVESTIGATE_ROUNDS,
)
from .state import GraphState


def after_diagnose(state: GraphState) -> str:
    confidence = state.get("confidence")
    value = DEFAULT_CONFIDENCE if confidence is None else confidence
    rounds = state.get("investigate_rounds") or 0
    if value < CONFIDENCE_RETRY_THRESHOLD and rounds < MAX_INVESTIGATE_ROUNDS:
        notes = (state.get("investigation_notes") or "").strip()
        gained = bool(state.get("investigate_gained_observations"))
        if notes and not gained:
            return "propose"
        return "investigate"
    return "propose"


def after_propose(state: GraphState) -> str:
    return "confirm" if state.get("proposed_action") else "end"


def after_confirm(state: GraphState) -> str:
    return "execute" if state.get("human_decision") == "yes" else "end"
