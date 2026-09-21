from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Observation:
    source: str
    ok: bool
    payload: str
    error: str | None = None


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str


@dataclass(frozen=True)
class Action:
    tool: str
    target: str
    reason: str
    risk: str


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None


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
class ChatResult:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
