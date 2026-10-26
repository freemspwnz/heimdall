from heimdall.application.models import ToolCall
from heimdall.application.protocols import Docker, Loki, VictoriaMetrics
from heimdall.domain.models import Observation

from ...constants import LOG_LOOKBACK, MAX_OBSERVATION_LINES
from .registry import DOCKER_INSPECT, DOCKER_LOGS, DOCKER_PS, LOKI_QUERY, VM_QUERY


class Tools:
    def __init__(
        self,
        docker: Docker,
        loki: Loki,
        vm: VictoriaMetrics,
    ) -> None:
        self._docker = docker
        self._loki = loki
        self._vm = vm

    async def __call__(self, call: ToolCall) -> Observation:
        arguments = call.arguments
        if call.name == LOKI_QUERY:
            since = self._text(arguments.get("since")) or LOG_LOOKBACK
            return await self._loki.query(
                self._text(arguments.get("query")),
                since=since,
            )
        if call.name == VM_QUERY:
            return await self._vm.query(self._text(arguments.get("query")))
        if call.name == DOCKER_PS:
            return await self._docker.ps()
        if call.name == DOCKER_INSPECT:
            return await self._docker.inspect(self._text(arguments.get("name")))
        if call.name == DOCKER_LOGS:
            tail = self._tail(arguments.get("tail"))
            return await self._docker.logs(self._text(arguments.get("name")), tail=tail)
        return Observation(
            source=call.name,
            ok=False,
            payload="",
            error=f"unknown tool: {call.name}",
        )

    @staticmethod
    def _tail(value: object) -> int:
        if isinstance(value, bool):
            return MAX_OBSERVATION_LINES
        if isinstance(value, int):
            candidate = value
        elif isinstance(value, str) and value.strip().isdigit():
            candidate = int(value.strip())
        else:
            return MAX_OBSERVATION_LINES
        return max(1, min(candidate, MAX_OBSERVATION_LINES))

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, str):
            return value
        return ""
