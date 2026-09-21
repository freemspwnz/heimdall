from __future__ import annotations

import json
import time

import aiohttp

from heimdall.constants import HTTP_TIMEOUT_SECONDS
from heimdall.models import Observation
from heimdall.truncate import truncate_payload

_SOURCE = "loki"
_QUERY_PATH = "/loki/api/v1/query_range"
_QUERY_LIMIT = 5000
_EMPTY_PAYLOAD = "no streams"


def _since_seconds(since: str) -> float:
    if len(since) < 2:
        return 15 * 60
    unit = since[-1]
    try:
        amount = float(since[:-1])
    except ValueError:
        return 15 * 60
    multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    return amount * multipliers.get(unit, 60.0)


def _flatten_log_lines(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, list):
        return []
    lines: list[str] = []
    for stream in result:
        if not isinstance(stream, dict):
            continue
        values = stream.get("values")
        if not isinstance(values, list):
            continue
        for pair in values:
            if isinstance(pair, list) and len(pair) >= 2 and isinstance(pair[1], str):
                lines.append(pair[1])
    return lines


class LokiClient:
    def __init__(self, base_url: str, session: aiohttp.ClientSession) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session

    async def query(self, logql: str, since: str = "15m") -> Observation:
        url = f"{self._base_url}{_QUERY_PATH}"
        end = time.time()
        start = end - _since_seconds(since)
        params: dict[str, str] = {
            "query": logql,
            "start": str(int(start * 1_000_000_000)),
            "end": str(int(end * 1_000_000_000)),
            "limit": str(_QUERY_LIMIT),
            "direction": "forward",
        }
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        try:
            async with self._session.get(url, params=params, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return Observation(
                        source=_SOURCE,
                        ok=False,
                        payload="",
                        error=f"{resp.status} {text}",
                    )
                try:
                    parsed: object = json.loads(text)
                except json.JSONDecodeError as exc:
                    return Observation(
                        source=_SOURCE,
                        ok=False,
                        payload="",
                        error=str(exc),
                    )
                lines = _flatten_log_lines(parsed)
                if not lines:
                    return Observation(source=_SOURCE, ok=True, payload=_EMPTY_PAYLOAD)
                return Observation(
                    source=_SOURCE,
                    ok=True,
                    payload=truncate_payload("\n".join(lines)),
                )
        except TimeoutError as exc:
            return Observation(
                source=_SOURCE,
                ok=False,
                payload="",
                error=str(exc) or "timeout",
            )
        except aiohttp.ClientError as exc:
            return Observation(
                source=_SOURCE,
                ok=False,
                payload="",
                error=str(exc),
            )
