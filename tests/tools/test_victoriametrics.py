import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from heimdall.tools import VictoriaMetricsClient


def _response(status: int, body: dict[str, object] | str) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    payload = body if isinstance(body, str) else json.dumps(body)
    resp.text = AsyncMock(return_value=payload)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


@pytest.mark.asyncio
async def test_vm_query_formats_vector() -> None:
    body: dict[str, object] = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"__name__": "pg_up", "instance": "postgres-exporter"},
                    "value": [1710000000, "1"],
                }
            ],
        },
    }
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, body))
    client = VictoriaMetricsClient("http://vm:8428", session)
    obs = await client.query("pg_up")
    assert obs.ok is True
    assert obs.source == "victoriametrics"
    assert "pg_up" in obs.payload
    assert "1" in obs.payload
    session.get.assert_called_once()
    url = session.get.call_args.args[0]
    params = session.get.call_args.kwargs["params"]
    assert url.endswith("/api/v1/query")
    assert params["query"] == "pg_up"


@pytest.mark.asyncio
async def test_vm_http_500_is_observation_error() -> None:
    session = MagicMock()
    session.get = MagicMock(return_value=_response(500, "boom"))
    client = VictoriaMetricsClient("http://vm:8428", session)
    obs = await client.query("pg_up")
    assert obs.ok is False
    assert "500" in (obs.error or "")


@pytest.mark.asyncio
async def test_vm_timeout_becomes_observation_error() -> None:
    session = MagicMock()

    class _Timeout:
        async def __aenter__(self) -> None:
            raise TimeoutError("slow")

        async def __aexit__(self, *args: object) -> None:
            return None

    session.get = MagicMock(return_value=_Timeout())
    client = VictoriaMetricsClient("http://vm:8428", session)
    obs = await client.query("pg_up")
    assert obs.ok is False
    assert obs.error


@pytest.mark.asyncio
async def test_vm_client_error_becomes_observation_error() -> None:
    import aiohttp

    session = MagicMock()

    class _ClientErr:
        async def __aenter__(self) -> None:
            raise aiohttp.ClientError("boom")

        async def __aexit__(self, *args: object) -> None:
            return None

    session.get = MagicMock(return_value=_ClientErr())
    client = VictoriaMetricsClient("http://vm:8428", session)
    obs = await client.query("pg_up")
    assert obs.ok is False
    assert "boom" in (obs.error or "")


@pytest.mark.asyncio
async def test_vm_http_500_error_is_truncated() -> None:
    huge = "x" * 8000
    session = MagicMock()
    session.get = MagicMock(return_value=_response(500, huge))
    client = VictoriaMetricsClient("http://vm:8428", session)
    obs = await client.query("pg_up")
    assert obs.ok is False
    assert obs.error is not None
    assert len(obs.error) <= 4010
    assert "500" in obs.error


@pytest.mark.asyncio
async def test_vm_empty_result_is_ok() -> None:
    body: dict[str, object] = {
        "status": "success",
        "data": {"resultType": "vector", "result": []},
    }
    session = MagicMock()
    session.get = MagicMock(return_value=_response(200, body))
    client = VictoriaMetricsClient("http://vm:8428", session)
    obs = await client.query("pg_up")
    assert obs.ok is True
    assert obs.source == "victoriametrics"
    assert obs.payload == "no data"
