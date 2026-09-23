from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from heimdall.models import Action

RunEventType = Literal["status", "busy", "hitl", "report", "error"]


@dataclass(frozen=True)
class RunEvent:
    type: RunEventType
    text: str = ""
    run_id: str | None = None
    action: Action | None = None
