from typing import Protocol

from heimdall.models import ChatMessage, ChatResult, ToolSpec


class ChatUnavailable(Exception):
    pass


class EmbeddingsUnavailable(Exception):
    pass


class ChatModel(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult: ...


class Embedder(Protocol):
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]: ...
