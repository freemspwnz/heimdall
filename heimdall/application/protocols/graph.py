from collections.abc import AsyncIterator
from typing import Literal, Protocol

from ..models import RunEvent


class Graph(Protocol):
    def start(
        self,
        question: str,
    ) -> AsyncIterator[RunEvent]: ...

    async def decide(
        self,
        run_id: str,
        accepted: bool,
    ) -> Literal["unknown", "not_waiting", "ok"]: ...
