import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from heimdall.constants import MAX_OBSERVATION_LINES
from heimdall.tools import LokiClient


def _response(status: int, body: dict[str, object] | str) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    payload = body if isinstance(body, str) else json.dumps(body)
    resp.text = AsyncMock(return_value=payload)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


@pytest.mark.asyncio
async def test_loki_query_ok_truncates_and_flattens() -> None:
    body: dict[str, object] = {
        "data": {
            "result": [
                {
                    "stream": {"container": "postgres"},
                    "values": [[str(i), f"log-{i}"] for i in range(120)],
                }
            ]
        }
    }
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, body))
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{container="postgres"}', since="15m")
    assert obs.ok is True
    assert obs.source == "loki"
    payload_lines = obs.payload.splitlines()
    assert len(payload_lines) <= 100
    assert payload_lines == [f"log-{i}" for i in range(20, 120)]
    assert "log-0" not in obs.payload
    session.get.assert_called_once()
    url = session.get.call_args.args[0]
    params = session.get.call_args.kwargs["params"]
    assert url.endswith("/loki/api/v1/query_range")
    assert params["query"] == '{container="postgres"}'
    assert params["direction"] == "backward"
    assert params["limit"] == str(MAX_OBSERVATION_LINES)


@pytest.mark.asyncio
async def test_loki_timeout_becomes_observation_error() -> None:
    session = MagicMock()

    class _Timeout:
        async def __aenter__(self) -> None:
            raise TimeoutError("slow")

        async def __aexit__(self, *args: object) -> None:
            return None

    session.get = MagicMock(return_value=_Timeout())
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{container="postgres"}')
    assert obs.ok is False
    assert obs.error


@pytest.mark.asyncio
async def test_loki_http_500_is_observation_error() -> None:
    session = MagicMock()
    session.get = MagicMock(return_value=_response(500, "nope"))
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{job="traefik"}')
    assert obs.ok is False
    assert "500" in (obs.error or "")


@pytest.mark.asyncio
async def test_loki_client_error_becomes_observation_error() -> None:
    import aiohttp

    session = MagicMock()

    class _ClientErr:
        async def __aenter__(self) -> None:
            raise aiohttp.ClientError("boom")

        async def __aexit__(self, *args: object) -> None:
            return None

    session.get = MagicMock(return_value=_ClientErr())
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{container="postgres"}')
    assert obs.ok is False
    assert "boom" in (obs.error or "")


@pytest.mark.asyncio
async def test_loki_http_500_error_is_truncated() -> None:
    huge = "x" * 8000
    session = MagicMock()
    session.get = MagicMock(return_value=_response(500, huge))
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{job="traefik"}')
    assert obs.ok is False
    assert obs.error is not None
    assert len(obs.error) <= 4010
    assert "500" in obs.error


@pytest.mark.asyncio
async def test_loki_empty_streams_is_ok() -> None:
    body: dict[str, object] = {"data": {"result": []}}
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, body))
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{container="missing"}')
    assert obs.ok is True
    assert obs.source == "loki"
    assert obs.payload == "no streams"
