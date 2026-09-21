from dataclasses import dataclass, field

from heimdall.models import ChatMessage, ChatResult, ToolCall, ToolSpec

KEYWORDS = [
    "postgres",
    "exporter",
    "traefik",
    "whoami",
    "sing-box",
    "3x-ui",
    "tunnel",
    "loki",
    "jellyfin",
    "restart",
]


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
        self.calls.append({"messages": messages, "tools": tools})
        if not self._turns:
            return ChatResult(content="", tool_calls=[])
        turn = self._turns.pop(0)
        return ChatResult(content=turn.content, tool_calls=list(turn.tool_calls))


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            t = text.lower()
            out.append([float(t.count(k)) for k in KEYWORDS])
        return out
