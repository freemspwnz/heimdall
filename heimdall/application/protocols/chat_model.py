from typing import Protocol

from ..models import ChatMessage, ChatResult, ToolSpec


class ChatModel(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult: ...
