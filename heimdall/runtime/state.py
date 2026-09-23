from __future__ import annotations

from typing import Any

from heimdall.graph.prompts import EMPTY_REPORT
from heimdall.models import Action


def is_interrupted(state: dict[str, Any]) -> bool:
    return bool(state.get("__interrupt__"))


def pending_action(state: dict[str, Any]) -> Action | None:
    interrupts = state.get("__interrupt__")
    if not isinstance(interrupts, list | tuple) or not interrupts:
        return None
    value = getattr(interrupts[0], "value", None)
    if not isinstance(value, dict):
        return None
    proposed = value.get("proposed_action")
    if not isinstance(proposed, dict):
        return None
    return Action(
        tool=text(proposed.get("tool")) or "restart",
        target=text(proposed.get("target")),
        reason=text(proposed.get("reason")),
        risk=text(proposed.get("risk")),
    )


def report(state: dict[str, Any]) -> str:
    value = state.get("report")
    if isinstance(value, str) and value:
        return value
    return EMPTY_REPORT


def text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
