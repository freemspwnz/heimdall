from dataclasses import dataclass, field

from heimdall.application.models import ChatMessage, ChatResult, ToolCall, ToolSpec


@dataclass
class ScriptedTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class FakeChatModel:
    def __init__(self, turns: list[ScriptedTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools) if tools is not None else None,
            }
        )
        if not self._turns:
            return ChatResult(content="", tool_calls=[])
        turn = self._turns.pop(0)
        return ChatResult(content=turn.content, tool_calls=list(turn.tool_calls))
