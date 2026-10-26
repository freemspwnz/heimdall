from dataclasses import dataclass, field
from typing import Literal

from heimdall.domain.models import Action


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None


@dataclass(frozen=True)
class ChatResult:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


RunEventType = Literal["status", "busy", "hitl", "report", "error"]


@dataclass(frozen=True)
class RunEvent:
    type: RunEventType
    text: str = ""
    run_id: str | None = None
    action: Action | None = None
