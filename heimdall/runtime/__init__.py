from __future__ import annotations

from typing import TYPE_CHECKING, Any

from heimdall.runtime.events import RunEvent, RunEventType

if TYPE_CHECKING:
    from heimdall.runtime.runner import AskRunner

__all__ = [
    "AskRunner",
    "RunEvent",
    "RunEventType",
]


def __getattr__(name: str) -> Any:
    if name == "AskRunner":
        from heimdall.runtime.runner import AskRunner

        return AskRunner
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
