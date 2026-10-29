from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel

from ..prompts import ANSWER_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import _context, _final_report, _parse_json_object, _text


class answer:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def __call__(self, state: GraphState) -> StateUpdate:
        result = await self._chat.complete(
            [
                ChatMessage(role="system", content=ANSWER_SYSTEM),
                ChatMessage(role="user", content=_context(state)),
            ],
            node="answer",
        )
        data = _parse_json_object(result.content)
        report = _text(data.get("report"))
        return {"report": _final_report(state, report)}
