from heimdall.application.models import ToolCall
from heimdall.domain.models import Observation

from ...constants import LOG_LOOKBACK, MAX_OBSERVATION_LINES
from ...deps import GraphDeps
from .registry import DOCKER_INSPECT, DOCKER_LOGS, DOCKER_PS, LOKI_QUERY, VM_QUERY


async def run_tool(deps: GraphDeps, call: ToolCall) -> Observation:
    arguments = call.arguments
    if call.name == LOKI_QUERY:
        since = _text(arguments.get("since")) or LOG_LOOKBACK
        return await deps.loki.query(_text(arguments.get("query")), since=since)
    if call.name == VM_QUERY:
        return await deps.vm.query(_text(arguments.get("query")))
    if call.name == DOCKER_PS:
        return await deps.docker.ps()
    if call.name == DOCKER_INSPECT:
        return await deps.docker.inspect(_text(arguments.get("name")))
    if call.name == DOCKER_LOGS:
        tail = _tail(arguments.get("tail"))
        return await deps.docker.logs(_text(arguments.get("name")), tail=tail)
    return Observation(
        source=call.name,
        ok=False,
        payload="",
        error=f"unknown tool: {call.name}",
    )


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


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
