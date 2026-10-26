from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel

from ...constants import DEFAULT_CONFIDENCE
from ..prompts import DIAGNOSE_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import _append, _context, _parse_json_object, _system_prompt, _text


class diagnose:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def __call__(self, state: GraphState) -> StateUpdate:
        result = await self._chat.complete(
            [
                ChatMessage(
                    role="system", content=_system_prompt(DIAGNOSE_SYSTEM, state)
                ),
                ChatMessage(role="user", content=_context(state)),
            ]
        )
        data = _parse_json_object(result.content)
        report = _text(data.get("report"))
        unknown = _text(data.get("unknown"))
        if unknown:
            report = _append(report, f"Не проверено: {unknown}")  # noqa: RUF001
        return {
            "hypothesis": _text(data.get("hypothesis")) or None,
            "confidence": self._confidence(data.get("confidence")),
            "report": report or None,
        }

    @staticmethod
    def _confidence(value: object) -> float:
        if isinstance(value, bool):
            return DEFAULT_CONFIDENCE
        if isinstance(value, int | float):
            candidate = float(value)
        elif isinstance(value, str):
            try:
                candidate = float(value.strip())
            except ValueError:
                return DEFAULT_CONFIDENCE
        else:
            return DEFAULT_CONFIDENCE
        if 0.0 <= candidate <= 1.0:
            return candidate
        return DEFAULT_CONFIDENCE
