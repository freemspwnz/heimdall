from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    source: str
    ok: bool
    payload: str
    error: str | None = None
    tool: str = ""
    target: str = ""
    query: str = ""
    since: str = ""


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
