from typing import Protocol

from heimdall.domain.models import Observation


class VictoriaMetrics(Protocol):
    async def query(self, metricsql: str) -> Observation: ...
