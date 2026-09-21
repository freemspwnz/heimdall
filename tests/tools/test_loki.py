import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from heimdall.tools.loki import LokiClient


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
    assert obs.payload.count("\n") + 1 <= 100
    session.get.assert_called()


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
async def test_loki_empty_streams_is_ok() -> None:
    body: dict[str, object] = {"data": {"result": []}}
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, body))
    client = LokiClient("http://loki:3100", session)
    obs = await client.query('{container="missing"}')
    assert obs.ok is True
    assert obs.source == "loki"
    assert obs.payload == "no streams"
