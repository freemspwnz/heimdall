import json

import aiohttp

from heimdall.constants import HTTP_TIMEOUT_SECONDS
from heimdall.models import Observation
from heimdall.truncate import truncate_payload

_SOURCE = "victoriametrics"
_QUERY_PATH = "/api/v1/query"
_EMPTY_PAYLOAD = "no data"


def _format_metric(metric: object) -> str:
    if not isinstance(metric, dict):
        return ""
    name_raw = metric.get("__name__", "")
    name = name_raw if isinstance(name_raw, str) else ""
    labels: list[str] = []
    for key, value in metric.items():
        if key == "__name__":
            continue
        if isinstance(key, str) and isinstance(value, str):
            labels.append(f'{key}="{value}"')
    if labels:
        return f"{name}{{{','.join(labels)}}}"
    return name


def _flatten_vector(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, list):
        return []
    lines: list[str] = []
    for sample in result:
        if not isinstance(sample, dict):
            continue
        metric_line = _format_metric(sample.get("metric"))
        value = sample.get("value")
        if isinstance(value, list) and len(value) >= 2:
            raw = value[1]
            value_str = raw if isinstance(raw, str) else str(raw)
            lines.append(f"{metric_line} = {value_str}")
    return lines


class VictoriaMetricsClient:
    def __init__(self, base_url: str, session: aiohttp.ClientSession) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session

    async def query(self, metricsql: str) -> Observation:
        url = f"{self._base_url}{_QUERY_PATH}"
        params: dict[str, str] = {"query": metricsql}
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
                lines = _flatten_vector(parsed)
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
