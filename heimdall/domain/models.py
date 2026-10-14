from dataclasses import dataclass


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
