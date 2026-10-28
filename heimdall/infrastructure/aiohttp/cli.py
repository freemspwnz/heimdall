import json
from collections.abc import AsyncIterator
from typing import cast
from urllib.parse import urljoin

import aiohttp

from heimdall.application.exceptions import IngestError
from heimdall.application.models import RunEvent, RunEventType
from heimdall.domain.models import Action

# SSE ask can run for minutes (GigaChat + tools); do not apply a total timeout.
_ASK_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=10)
_RESUME_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10)
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5, sock_connect=5)
_INGEST_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=10)


def make_client_session() -> aiohttp.ClientSession:
    """Session safe to reuse after SSE: force-close avoids stale keep-alive sockets."""
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(force_close=True),
        timeout=_ASK_TIMEOUT,
    )


class AgentClient:
    def __init__(
        self,
        base_url: str,
        http: aiohttp.ClientSession,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._http = http

    async def probe(self) -> None:
        url = urljoin(self._base_url, "health")
        async with self._http.get(url, timeout=_PROBE_TIMEOUT) as resp:
            resp.raise_for_status()

    async def ask(self, question: str) -> AsyncIterator[RunEvent]:
        url = urljoin(self._base_url, "v1/ask")
        async with self._http.post(
            url,
            json={"question": question},
            timeout=_ASK_TIMEOUT,
            headers={"Connection": "close"},
        ) as resp:
            resp.raise_for_status()
            async for event in self._iter_sse(resp.content):
                yield event

    async def resume(self, run_id: str, decision: bool) -> None:
        url = urljoin(self._base_url, f"v1/runs/{run_id}/resume")
        async with self._http.post(
            url,
            json={"decision": decision},
            timeout=_RESUME_TIMEOUT,
            headers={"Connection": "close"},
        ) as resp:
            resp.raise_for_status()

    async def ingest(self) -> int:
        url = urljoin(self._base_url, "v1/ingest")
        async with self._http.post(
            url,
            timeout=_INGEST_TIMEOUT,
            headers={"Connection": "close"},
        ) as resp:
            if resp.status >= 400:
                raise IngestError(await self._response_detail(resp))
            payload = await resp.json()
            return int(payload["count"])

    async def _iter_sse(self, content: aiohttp.StreamReader) -> AsyncIterator[RunEvent]:
        buffer = ""
        async for raw in content.iter_any():
            buffer += raw.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event = self._parse_sse_block(block)
                if event is not None:
                    yield event

    @staticmethod
    def _parse_sse_block(block: str) -> RunEvent | None:
        event_type: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event_type is None or not data_lines:
            return None
        payload = json.loads("\n".join(data_lines))
        action = None
        raw_action = payload.get("action")
        if isinstance(raw_action, dict):
            action = Action(
                tool=str(raw_action.get("tool", "")),
                target=str(raw_action.get("target", "")),
                reason=str(raw_action.get("reason", "")),
                risk=str(raw_action.get("risk", "")),
            )
        run_id = payload.get("run_id")
        return RunEvent(
            type=cast(RunEventType, event_type),
            text=str(payload.get("text", "")),
            run_id=str(run_id) if run_id is not None else None,
            action=action,
        )

    @staticmethod
    async def _response_detail(resp: aiohttp.ClientResponse) -> str:
        try:
            payload = await resp.json(content_type=None)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail:
                return detail
        reason = resp.reason or ""
        return reason or str(resp.status)
