import json
import time

import aiohttp

from heimdall.domain.models import Observation

from ..constants import MAX_OBSERVATION_CHARS, MAX_OBSERVATION_LINES
from .utils import fail, ok, timeout, truncate_payload

_SOURCE = "loki"
_QUERY_PATH = "/loki/api/v1/query_range"
_QUERY_LIMIT = MAX_OBSERVATION_LINES
_EMPTY_PAYLOAD = "no streams"
_LABEL_KEYS = ("container_name", "container", "service")


class LokiClient:
    def __init__(self, base_url: str, session: aiohttp.ClientSession) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session

    async def query(self, logql: str, since: str = "15m") -> Observation:
        url = f"{self._base_url}{_QUERY_PATH}"
        end = time.time()
        start = end - self._since_seconds(since)
        params: dict[str, str] = {
            "query": logql,
            "start": str(int(start * 1_000_000_000)),
            "end": str(int(end * 1_000_000_000)),
            "limit": str(_QUERY_LIMIT),
            "direction": "backward",
        }

        try:
            async with self._session.get(url, params=params, timeout=timeout()) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return fail(_SOURCE, f"{resp.status} {truncate_payload(text)}")
                try:
                    parsed: object = json.loads(text)
                except json.JSONDecodeError as exc:
                    return fail(_SOURCE, str(exc))
                lines = self._flatten_log_lines(parsed)
                if not lines:
                    return ok(_SOURCE, _EMPTY_PAYLOAD)
                return ok(_SOURCE, truncate_payload(self._tail_window(lines)))
        except TimeoutError as exc:
            return fail(_SOURCE, str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return fail(_SOURCE, str(exc))

    @staticmethod
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

    @staticmethod
    def _entry_ts(raw: object) -> int:
        if isinstance(raw, bool):
            return 0
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        return 0

    @staticmethod
    def _stream_prefix(stream: dict[str, object]) -> str:
        labels = stream.get("stream")
        if not isinstance(labels, dict):
            return ""
        for key in _LABEL_KEYS:
            value = labels.get(key)
            if isinstance(value, str) and value:
                return f"{key}={value} "
        return ""

    def _flatten_log_lines(self, payload: object) -> list[str]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        if not isinstance(result, list):
            return []
        entries: list[tuple[int, str]] = []
        for stream in result:
            if not isinstance(stream, dict):
                continue
            values = stream.get("values")
            if not isinstance(values, list):
                continue
            prefix = self._stream_prefix(stream)
            for pair in values:
                if (
                    isinstance(pair, list)
                    and len(pair) >= 2
                    and isinstance(pair[1], str)
                ):
                    entries.append((self._entry_ts(pair[0]), f"{prefix}{pair[1]}"))
        entries.sort(key=lambda item: item[0])
        return [line for _, line in entries]

    @staticmethod
    def _tail_window(lines: list[str]) -> str:
        window = lines[-MAX_OBSERVATION_LINES:]
        text = "\n".join(window)
        if len(text) > MAX_OBSERVATION_CHARS:
            text = text[-MAX_OBSERVATION_CHARS:]
        return text
