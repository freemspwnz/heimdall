import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from heimdall.tools import DockerClient

JsonBody = dict[str, object] | list[object]


def _response(status: int, body: JsonBody | str | bytes) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    if isinstance(body, bytes):
        resp.read = AsyncMock(return_value=body)
        resp.text = AsyncMock(return_value=body.decode("utf-8", errors="replace"))
    else:
        payload = body if isinstance(body, str) else json.dumps(body)
        resp.text = AsyncMock(return_value=payload)
        resp.read = AsyncMock(return_value=payload.encode())
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


@pytest.mark.asyncio
async def test_docker_client_rejects_non_unix_host() -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="unix://"):
        DockerClient("tcp://127.0.0.1:2375", session)

    session = MagicMock()
    session.get = MagicMock(
        return_value=_response(
            200,
            [
                {
                    "Names": ["/postgres"],
                    "State": "running",
                    "Status": "Up 6 days (healthy)",
                }
            ],
        )
    )
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.ps()
    assert obs.ok is True
    assert obs.source == "docker"
    assert "postgres" in obs.payload
    assert "healthy" in obs.payload.lower() or "running" in obs.payload.lower()
    session.get.assert_called_once()
    url = session.get.call_args.args[0]
    params = session.get.call_args.kwargs["params"]
    assert url == "http://localhost/containers/json"
    assert params["all"] == "1"


@pytest.mark.asyncio
async def test_restart_postgres_allowed() -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=_response(204, ""))
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.restart("postgres")
    assert obs.ok is True
    assert obs.source == "docker"
    session.post.assert_called()
    url = session.post.call_args.args[0]
    assert url == "http://localhost/containers/postgres/restart"


@pytest.mark.asyncio
async def test_restart_vaultwarden_blocked_without_http() -> None:
    session = MagicMock()
    session.post = MagicMock()
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.restart("vaultwarden")
    assert obs.ok is False
    assert "allowlist" in (obs.error or "").lower()
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_restart_gitea_blocked_without_http() -> None:
    session = MagicMock()
    session.post = MagicMock()
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.restart("gitea")
    assert obs.ok is False
    assert "allowlist" in (obs.error or "").lower()
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_docker_inspect_returns_container_json() -> None:
    body: dict[str, object] = {
        "Name": "/postgres",
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
    }
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, body))
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.inspect("postgres")
    assert obs.ok is True
    assert obs.source == "docker"
    assert "postgres" in obs.payload
    assert "healthy" in obs.payload.lower() or "running" in obs.payload.lower()
    session.get.assert_called_once()
    url = session.get.call_args.args[0]
    assert url == "http://localhost/containers/postgres/json"


@pytest.mark.asyncio
async def test_docker_logs_returns_text() -> None:
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, "ready for connections"))
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.logs("postgres")
    assert obs.ok is True
    assert obs.source == "docker"
    assert "ready for connections" in obs.payload
    session.get.assert_called_once()
    url = session.get.call_args.args[0]
    params = session.get.call_args.kwargs["params"]
    assert url == "http://localhost/containers/postgres/logs"
    assert params["stdout"] == "1"
    assert params["stderr"] == "1"
    assert params["tail"] == "100"


@pytest.mark.asyncio
async def test_docker_ps_http_500_is_observation_error() -> None:
    session = MagicMock()
    session.get = MagicMock(return_value=_response(500, "engine down"))
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.ps()
    assert obs.ok is False
    assert obs.source == "docker"
    assert "500" in (obs.error or "")


@pytest.mark.asyncio
async def test_docker_ps_timeout_becomes_observation_error() -> None:
    session = MagicMock()

    class _Timeout:
        async def __aenter__(self) -> None:
            raise TimeoutError("slow")

        async def __aexit__(self, *args: object) -> None:
            return None

    session.get = MagicMock(return_value=_Timeout())
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.ps()
    assert obs.ok is False
    assert obs.error


@pytest.mark.asyncio
async def test_docker_ps_client_error_becomes_observation_error() -> None:
    import aiohttp

    session = MagicMock()

    class _ClientErr:
        async def __aenter__(self) -> None:
            raise aiohttp.ClientError("boom")

        async def __aexit__(self, *args: object) -> None:
            return None

    session.get = MagicMock(return_value=_ClientErr())
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.ps()
    assert obs.ok is False
    assert "boom" in (obs.error or "")


@pytest.mark.asyncio
async def test_docker_logs_demuxes_multiplexed_frames() -> None:
    payload = b"ready for connections\n"
    frame = b"\x01\x00\x00\x00" + len(payload).to_bytes(4, "big") + payload
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, frame))
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.logs("postgres")
    assert obs.ok is True
    assert obs.payload == "ready for connections\n"


@pytest.mark.asyncio
async def test_docker_http_500_error_is_truncated() -> None:
    huge = "x" * 8000
    session = MagicMock()
    session.get = MagicMock(return_value=_response(500, huge))
    client = DockerClient("unix:///var/run/docker.sock", session)
    obs = await client.ps()
    assert obs.ok is False
    assert obs.error is not None
    assert len(obs.error) <= 4010
    assert "500" in obs.error
