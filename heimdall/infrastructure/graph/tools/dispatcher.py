from dataclasses import replace

from heimdall.application.models import ToolCall
from heimdall.application.protocols import Docker, Logger, Loki, VictoriaMetrics
from heimdall.domain.models import Observation

from ...constants import LOG_LOOKBACK, MAX_OBSERVATION_LINES
from .registry import DOCKER_INSPECT, DOCKER_LOGS, DOCKER_PS, LOKI_QUERY, VM_QUERY


class Tools:
    def __init__(
        self,
        docker: Docker,
        loki: Loki,
        vm: VictoriaMetrics,
        logger: Logger,
    ) -> None:
        self._docker = docker
        self._loki = loki
        self._vm = vm
        self._logger = logger

    async def __call__(self, call: ToolCall) -> Observation:
        observation = await self._run(call)
        self._logger.info(self._observe_line(observation))
        return observation

    async def _run(self, call: ToolCall) -> Observation:
        arguments = call.arguments
        if call.name == LOKI_QUERY:
            since = self._text(arguments.get("since")) or LOG_LOOKBACK
            query = self._text(arguments.get("query"))
            return self._stamp(
                await self._loki.query(query, since=since),
                tool=LOKI_QUERY,
                query=query,
                since=since,
            )
        if call.name == VM_QUERY:
            query = self._text(arguments.get("query"))
            return self._stamp(
                await self._vm.query(query),
                tool=VM_QUERY,
                query=query,
            )
        if call.name == DOCKER_PS:
            return self._stamp(await self._docker.ps(), tool=DOCKER_PS)
        if call.name == DOCKER_INSPECT:
            target = self._text(arguments.get("name"))
            return self._stamp(
                await self._docker.inspect(target),
                tool=DOCKER_INSPECT,
                target=target,
            )
        if call.name == DOCKER_LOGS:
            tail = self._tail(arguments.get("tail"))
            target = self._text(arguments.get("name"))
            return self._stamp(
                await self._docker.logs(target, tail=tail),
                tool=DOCKER_LOGS,
                target=target,
            )
        return Observation(
            source=call.name,
            ok=False,
            payload="",
            error=f"unknown tool: {call.name}",
        )

    @staticmethod
    def _stamp(
        observation: Observation,
        *,
        tool: str,
        target: str = "",
        query: str = "",
        since: str = "",
    ) -> Observation:
        return replace(
            observation,
            tool=tool,
            target=target,
            query=query,
            since=since,
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

    @staticmethod
    def _observe_line(observation: Observation) -> str:
        tool = observation.tool or observation.source or "?"
        parts = [f"observe {tool}"]
        for label, value in (
            ("name", observation.target),
            ("since", observation.since),
            ("query", observation.query),
        ):
            if value:
                parts.append(f"{label}={value}")
        flag = "ok" if observation.ok else "err"
        detail = observation.payload if observation.ok else (observation.error or "")
        head = detail.replace("\n", " ")[:160]
        return f"{' '.join(parts)} {flag} {head}".rstrip()
