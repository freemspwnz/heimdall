import json

import pytest
from heimdall.infrastructure.graph.nodes.propose import propose
from heimdall.infrastructure.graph.state import GraphState
from heimdall.infrastructure.llms import FakeChatModel, ScriptedTurn

_DOWN = '{"State": {"Status": "exited", "ExitCode": 1}}'
_RUNNING = '{"State": {"Status": "running", "OOMKilled": true, "ExitCode": 137}}'
_UNHEALTHY = '{"State": {"Status": "running", "Health": {"Status": "unhealthy"}}}'
_HEALTH_ONLY = '{"State": {"Health": {"Status": "unhealthy"}}}'
_TRUNCATED_EXITED = (
    '{"Id":"abc","State":{"Status":"exited","Running":false,'
    '"Health":{"Status":"unhealthy","Log":['
)
_TRUNCATED_RUNNING = (
    '{"Id":"abc","State":{"Status":"running","OOMKilled":true,"ExitCode":137,'
    '"Health":{"Status":"healthy","Log":['
)


def _inspect(target: str, payload: str, *, ok: bool = True) -> dict[str, object]:
    return {
        "source": "docker",
        "ok": ok,
        "payload": payload,
        "error": None if ok else "timeout",
        "tool": "docker_inspect",
        "target": target,
        "query": "",
        "since": "",
    }


def _logs(target: str, payload: str) -> dict[str, object]:
    return {
        "source": "docker",
        "ok": True,
        "payload": payload,
        "error": None,
        "tool": "docker_logs",
        "target": target,
        "query": "",
        "since": "",
    }


def _state(observations: list[dict[str, object]]) -> GraphState:
    return {
        "question": "what about gitea",
        "retrieved_chunks": [],
        "observations": observations,
        "hypothesis": None,
        "confidence": 0.9,
        "investigate_rounds": 1,
        "proposed_action": None,
        "human_decision": None,
        "execution_result": None,
        "report": None,
        "investigation_notes": None,
        "investigate_gained_observations": False,
    }


async def _propose(
    observations: list[dict[str, object]],
    *,
    target: str = "gitea",
) -> dict[str, object]:
    body = json.dumps(
        {
            "action": {
                "tool": "restart",
                "target": target,
                "reason": "контейнер упал",
                "risk": "простой",
            },
            "report": "Нужен рестарт.",
        },
        ensure_ascii=False,
    )
    node = propose(FakeChatModel([ScriptedTurn(content=body)]))
    return await node(_state(observations))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [_DOWN, '{"State": {"Status": "dead"}}', '{"State": {"Status": "restarting"}}'],
)
async def test_restart_stands_when_inspect_shows_the_process_down(
    payload: str,
) -> None:
    update = await _propose([_inspect("gitea", payload)])
    action = update["proposed_action"]
    assert isinstance(action, dict)
    assert action["target"] == "gitea"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [_UNHEALTHY, _HEALTH_ONLY, _TRUNCATED_EXITED])
async def test_restart_stands_when_health_is_unhealthy(payload: str) -> None:
    update = await _propose([_inspect("gitea", payload)])
    assert update["proposed_action"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observations",
    [
        [],
        [_inspect("gitea", _RUNNING)],
        [_inspect("gitea", _TRUNCATED_RUNNING)],
        [_inspect("gitea", _DOWN, ok=False)],
        [_inspect("postgres", _DOWN)],
        [_logs("gitea", "FATAL: out of memory")],
        [_inspect("gitea", _DOWN), _inspect("gitea", _RUNNING)],
    ],
)
async def test_restart_is_dropped_without_a_down_inspect(
    observations: list[dict[str, object]],
) -> None:
    update = await _propose(observations)
    assert update["proposed_action"] is None
    report = update["report"]
    assert isinstance(report, str)
    assert report.startswith("Нужен рестарт.")


@pytest.mark.asyncio
async def test_later_inspect_of_the_same_container_wins() -> None:
    update = await _propose(
        [_inspect("gitea", _RUNNING), _inspect("gitea", _DOWN)],
    )
    assert update["proposed_action"] is not None


@pytest.mark.asyncio
async def test_any_container_outside_never_restart_can_be_proposed() -> None:
    update = await _propose([_inspect("jellyfin", _DOWN)], target="jellyfin")
    action = update["proposed_action"]
    assert isinstance(action, dict)
    assert action["target"] == "jellyfin"


@pytest.mark.asyncio
async def test_forbidden_target_is_dropped_even_when_inspect_is_down() -> None:
    update = await _propose([_inspect("postgres", _DOWN)], target="postgres")
    assert update["proposed_action"] is None
