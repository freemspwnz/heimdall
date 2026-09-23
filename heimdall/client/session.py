from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal, cast
from urllib.parse import urljoin

import aiohttp

from heimdall.models import Action
from heimdall.runtime.events import RunEvent, RunEventType


class AgentClient:
    def __init__(
        self,
        base_url: str,
        http: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._http = http
        self._owns_http = http is None

    async def _session(self) -> aiohttp.ClientSession:
        if self._http is None:
            self._http = aiohttp.ClientSession()
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.close()
            self._http = None

    async def ask(self, question: str) -> AsyncIterator[RunEvent]:
        session = await self._session()
        url = urljoin(self._base_url, "v1/ask")
        async with session.post(url, json={"question": question}) as resp:
            resp.raise_for_status()
            async for event in _iter_sse(resp.content):
                yield event

    async def resume(self, run_id: str, decision: Literal["yes", "no"]) -> None:
        session = await self._session()
        url = urljoin(self._base_url, f"v1/runs/{run_id}/resume")
        async with session.post(url, json={"decision": decision}) as resp:
            resp.raise_for_status()


async def _iter_sse(content: aiohttp.StreamReader) -> AsyncIterator[RunEvent]:
    buffer = ""
    async for raw in content.iter_any():
        buffer += raw.decode("utf-8", errors="replace")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            event = _parse_sse_block(block)
            if event is not None:
                yield event


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
