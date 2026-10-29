from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel, Logger
from heimdall.infrastructure.constants import DEFAULT_QUESTION_KIND, QUESTION_KINDS

from ..prompts import CLASSIFY_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import _parse_json_object, _text


class classify:
    def __init__(self, chat: ChatModel, logger: Logger) -> None:
        self._chat = chat
        self._logger = logger

    async def __call__(self, state: GraphState) -> StateUpdate:
        kind = DEFAULT_QUESTION_KIND
        try:
            result = await self._chat.complete(
                [
                    ChatMessage(role="system", content=CLASSIFY_SYSTEM),
                    ChatMessage(role="user", content=state["question"]),
                ],
                node="classify",
            )
            raw = _text(_parse_json_object(result.content).get("question_kind"))
            if raw in QUESTION_KINDS:
                kind = raw
        except Exception:
            self._logger.exception("classify failed; defaulting to diagnose")
            kind = DEFAULT_QUESTION_KIND
        self._logger.info("question_kind={}", kind)
        return {"question_kind": kind}
