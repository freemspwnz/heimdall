from dataclasses import asdict

from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel
from heimdall.domain.models import Action

from ...constants import NEVER_RESTART, RESTART_ALLOWLIST
from ..prompts import PROPOSE_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import _context, _final_report, _parse_json_object, _system_prompt, _text


class propose:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def __call__(self, state: GraphState) -> StateUpdate:
        result = await self._chat.complete(
            [
                ChatMessage(
                    role="system", content=_system_prompt(PROPOSE_SYSTEM, state)
                ),
                ChatMessage(role="user", content=_context(state)),
            ]
        )
        data = _parse_json_object(result.content)
        report = _text(data.get("report")) or _text(state.get("report"))
        action = self._parse_action(data.get("action"))
        if action is None:
            return {"proposed_action": None, "report": _final_report(state, report)}
        return {"proposed_action": asdict(action), "report": report or None}

    @staticmethod
    def _parse_action(value: object) -> Action | None:
        if not isinstance(value, dict):
            return None
        tool = _text(value.get("tool")) or "restart"
        if tool != "restart":
            return None
        target = _text(value.get("target"))
        if target not in RESTART_ALLOWLIST or target in NEVER_RESTART:
            return None
        return Action(
            tool=tool,
            target=target,
            reason=_text(value.get("reason")),
            risk=_text(value.get("risk")),
        )
