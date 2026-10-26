from typing import Protocol

from heimdall.domain.models import Observation


class Loki(Protocol):
    async def query(self, logql: str, since: str = "15m") -> Observation: ...
