import pytest
from heimdall.application.models import ToolCall
from heimdall.domain.models import Observation
from heimdall.infrastructure.graph.nodes.utils import _facts_block
from heimdall.infrastructure.graph.tools.dispatcher import Tools
from heimdall.infrastructure.graph.tools.registry import (
    DOCKER_INSPECT,
    DOCKER_LOGS,
    DOCKER_PS,
    LOKI_QUERY,
    VM_QUERY,
)
from tests.support import RecordingLogger


class _Docker:
    async def ps(self) -> Observation:
        return Observation(source="docker", ok=True, payload="ps")

    async def inspect(self, name: str) -> Observation:
        return Observation(source="docker", ok=True, payload=name)

    async def logs(self, name: str, tail: int = 100) -> Observation:
        return Observation(source="docker", ok=True, payload=f"{name}:{tail}")

    async def restart(self, name: str) -> Observation:
        return Observation(source="docker", ok=True, payload=name)


class _Loki:
    async def query(self, logql: str, since: str = "15m") -> Observation:
        return Observation(source="loki", ok=True, payload=logql)


class _Vm:
    async def query(self, metricsql: str) -> Observation:
        return Observation(source="victoriametrics", ok=True, payload=metricsql)


def _tools(logger: RecordingLogger | None = None) -> Tools:
    return Tools(_Docker(), _Loki(), _Vm(), logger or RecordingLogger())


def _call(tool: str, **arguments: object) -> ToolCall:
    return ToolCall(id="1", name=tool, arguments=arguments)


@pytest.mark.asyncio
async def test_loki_query_keeps_raw_query_and_default_window() -> None:
    query = '{container_name="postgres"} |~ "fatal"'
    obs = await _tools()(_call(LOKI_QUERY, query=query))
    assert obs.tool == LOKI_QUERY
    assert obs.query == query
    assert obs.since == "15m"
    assert obs.target == ""


@pytest.mark.asyncio
async def test_docker_logs_keep_container_name() -> None:
    obs = await _tools()(_call(DOCKER_LOGS, name="postgres", tail=20))
    assert obs.tool == DOCKER_LOGS
    assert obs.target == "postgres"
    assert obs.query == ""
    assert obs.since == ""
    assert obs.payload == "postgres:20"


@pytest.mark.asyncio
async def test_other_reads_keep_their_call() -> None:
    tools = _tools()
    inspect = await tools(_call(DOCKER_INSPECT, name="traefik"))
    ps = await tools(_call(DOCKER_PS))
    metric = await tools(_call(VM_QUERY, query="pg_up"))
    assert inspect.tool == DOCKER_INSPECT
    assert inspect.target == "traefik"
    assert ps.tool == DOCKER_PS
    assert ps.target == ""
    assert metric.tool == VM_QUERY
    assert metric.query == "pg_up"
    assert metric.target == ""


def test_facts_block_prints_call_and_skips_empty_fields() -> None:
    text = _facts_block(
        [
            {
                "source": "loki",
                "ok": True,
                "payload": "FATAL: x",
                "error": None,
                "tool": LOKI_QUERY,
                "target": "",
                "query": '{container_name="postgres"}',
                "since": "15m",
            },
            {
                "source": "docker",
                "ok": True,
                "payload": "running",
                "error": None,
                "tool": "",
                "target": "",
                "query": "",
                "since": "",
            },
        ]
    )
    assert 'loki_query since=15m query={container_name="postgres"}' in text
    assert "FATAL: x" in text
    assert "target=" not in text
    assert "[docker] ок\nrunning" in text


@pytest.mark.asyncio
async def test_tools_log_observation_line() -> None:
    recorded = RecordingLogger()
    tools = _tools(recorded)
    obs = await tools(_call(DOCKER_INSPECT, name="gitea"))
    assert obs.ok is True
    assert recorded.lines == ["observe docker_inspect name=gitea ok gitea"]
