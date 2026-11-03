from dataclasses import asdict
from pathlib import Path

from heimdall.application.models import ToolCall
from heimdall.domain.models import Observation
from heimdall.infrastructure.graph.nodes.preflight import preflight
from heimdall.infrastructure.graph.tools import READ_TOOLS
from tests.support import RecordingLogger, SilentLogger


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def __call__(self, call: ToolCall) -> Observation:
        self.calls.append(call)
        return Observation(source=call.name, ok=True, payload="ok", tool=call.name)


class FailingFirstTools(RecordingTools):
    async def __call__(self, call: ToolCall) -> Observation:
        self.calls.append(call)
        if len(self.calls) == 1:
            raise RuntimeError("client exploded")
        return Observation(source=call.name, ok=True, payload="ok", tool=call.name)


def _state(*, text: str, from_disk: bool = True) -> dict:
    chunk: dict[str, object] = {"text": text, "source": "runbooks/x.md"}
    if from_disk:
        chunk["from_disk"] = True
    return {
        "question": "q",
        "retrieved_chunks": [chunk],
        "observations": [],
    }


async def test_closed_fence_runs_and_strips() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())
    state = _state(
        text=(
            "before\n"
            "```heimdall-calls\n"
            "docker_ps\n"
            "docker_inspect name=postgres\n"
            "```\n"
            "after"
        )
    )

    result = await node(state)

    chunk = result["retrieved_chunks"][0]
    assert "heimdall-calls" not in chunk["text"]
    assert chunk["text"] == "before\nafter"
    assert len(result["observations"]) == 2
    assert [call.id for call in tools.calls] == ["preflight-1", "preflight-2"]
    assert tools.calls[1].arguments == {"name": "postgres"}


async def test_quoted_value_and_first_equals() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())

    await node(
        _state(
            text=(
                "```heimdall-calls\n"
                'loki_query query={container="postgres"} since=30m\n'
                'docker_logs name="traefik x" tail=100\n'
                "```"
            )
        )
    )

    assert tools.calls[0].arguments == {
        "query": '{container="postgres"}',
        "since": "30m",
    }
    assert tools.calls[1].arguments == {"name": "traefik x", "tail": "100"}


async def test_empty_closed_fence_strips_without_calls() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())

    result = await node(_state(text="before\n```heimdall-calls\n\n```\nafter"))

    assert result["retrieved_chunks"][0]["text"] == "before\nafter"
    assert tools.calls == []


async def test_unclosed_eof_records_error_keeps_text() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())
    text = "before\n```heimdall-calls\ndocker_ps"

    result = await node(_state(text=text))

    assert result["retrieved_chunks"][0]["text"] == text
    assert result["observations"][0]["error"].startswith(
        "bad heimdall-calls fence: unclosed"
    )
    assert tools.calls == []


async def test_unclosed_then_closed_via_new_opener() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())

    result = await node(
        _state(
            text=(
                "```heimdall-calls\n"
                "docker_inspect name=ignored\n"
                "```heimdall-calls\n"
                "docker_ps\n"
                "```"
            )
        )
    )

    assert result["observations"][0]["error"].startswith(
        "bad heimdall-calls fence: unclosed"
    )
    assert [call.name for call in tools.calls] == ["docker_ps"]
    assert result["retrieved_chunks"][0]["text"] == (
        "```heimdall-calls\ndocker_inspect name=ignored"
    )


async def test_bad_line_continues() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())

    result = await node(_state(text="```heimdall-calls\nnot-a-call\ndocker_ps\n```"))

    assert result["observations"][0]["error"].startswith("bad heimdall-calls line:")
    assert [call.name for call in tools.calls] == ["docker_ps"]


async def test_without_from_disk_ignores_fence() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())
    text = "```heimdall-calls\ndocker_ps\n```"

    result = await node(_state(text=text, from_disk=False))

    assert tools.calls == []
    assert result["retrieved_chunks"][0]["text"] == text


async def test_info_string_is_not_opener() -> None:
    tools = RecordingTools()
    node = preflight(tools, SilentLogger())
    text = "```heimdall-calls python\ndocker_ps\n```"

    result = await node(_state(text=text))

    assert tools.calls == []
    assert result["retrieved_chunks"][0]["text"] == text
    assert result["observations"] == []


async def test_tool_exception_continues() -> None:
    tools = FailingFirstTools()
    logger = RecordingLogger()
    node = preflight(tools, logger)

    result = await node(
        _state(text="```heimdall-calls\ndocker_ps\ndocker_inspect name=db\n```")
    )

    assert result["observations"][0] == asdict(
        Observation(
            source="docker_ps",
            ok=False,
            payload="",
            error="client exploded",
            tool="docker_ps",
        )
    )
    assert result["observations"][1]["ok"] is True
    assert [call.id for call in tools.calls] == ["preflight-1", "preflight-2"]
    assert logger.lines == ["preflight tool failed"]


async def test_demo_knowledge_fences_use_read_tools() -> None:
    runbooks = Path("docs/knowledge/runbooks")
    allowed_names = {tool.name for tool in READ_TOOLS}

    for filename in ("postgres.md", "traefik.md", "host.md", "redis.md"):
        tools = RecordingTools()
        node = preflight(tools, SilentLogger())

        await node(_state(text=(runbooks / filename).read_text()))

        assert tools.calls, filename
        assert {call.name for call in tools.calls} <= allowed_names
