from __future__ import annotations

import json
from urllib.parse import quote

import aiohttp

from heimdall.constants import HTTP_TIMEOUT_SECONDS, NEVER_RESTART, RESTART_ALLOWLIST
from heimdall.models import Observation
from heimdall.truncate import truncate_payload

_SOURCE = "docker"
_ENGINE_BASE = "http://localhost"


def _unix_socket_path(docker_host: str) -> str:
    if docker_host.startswith("unix://"):
        return docker_host.removeprefix("unix://")
    return docker_host


def _engine_url(path: str) -> str:
    return f"{_ENGINE_BASE}{path}"


def _container_segment(name: str) -> str:
    return quote(name, safe="")


def _timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)


def _fail(error: str) -> Observation:
    return Observation(source=_SOURCE, ok=False, payload="", error=error)


def _ok(payload: str) -> Observation:
    return Observation(source=_SOURCE, ok=True, payload=payload)


def _format_ps_line(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    names = item.get("Names")
    name = ""
    if isinstance(names, list) and names and isinstance(names[0], str):
        name = names[0].lstrip("/")
    state = item.get("State")
    status = item.get("Status")
    state_s = state if isinstance(state, str) else ""
    status_s = status if isinstance(status, str) else ""
    parts = [part for part in (name, state_s, status_s) if part]
    if not parts:
        return None
    return " ".join(parts)


def _looks_multiplexed(raw: bytes) -> bool:
    if len(raw) < 8:
        return False
    if raw[0] not in (1, 2):
        return False
    if raw[1:4] != b"\x00\x00\x00":
        return False
    size = int.from_bytes(raw[4:8], "big")
    return 8 + size <= len(raw)


def _demux_logs(raw: bytes) -> str:
    chunks: list[bytes] = []
    offset = 0
    while offset + 8 <= len(raw):
        size = int.from_bytes(raw[offset + 4 : offset + 8], "big")
        start = offset + 8
        end = start + size
        if end > len(raw):
            break
        chunks.append(raw[start:end])
        offset = end
    if not chunks:
        return raw.decode("utf-8", errors="replace")
    return b"".join(chunks).decode("utf-8", errors="replace")


def _logs_text(raw: bytes) -> str:
    if _looks_multiplexed(raw):
        return _demux_logs(raw)
    return raw.decode("utf-8", errors="replace")


class DockerClient:
    def __init__(self, docker_host: str, session: aiohttp.ClientSession) -> None:
        self._docker_host = docker_host
        self._session = session
        self._socket_path = _unix_socket_path(docker_host)

    async def ps(self) -> Observation:
        url = _engine_url("/containers/json")
        params: dict[str, str] = {"all": "1"}
        timeout = _timeout()
        try:
            async with self._session.get(url, params=params, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return _fail(f"{resp.status} {text}")
                try:
                    parsed: object = json.loads(text)
                except json.JSONDecodeError as exc:
                    return _fail(str(exc))
                if not isinstance(parsed, list):
                    return _fail("unexpected docker ps payload")
                lines: list[str] = []
                for item in parsed:
                    line = _format_ps_line(item)
                    if line is not None:
                        lines.append(line)
                return _ok(truncate_payload("\n".join(lines)))
        except TimeoutError as exc:
            return _fail(str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return _fail(str(exc))

    async def inspect(self, name: str) -> Observation:
        url = _engine_url(f"/containers/{_container_segment(name)}/json")
        timeout = _timeout()
        try:
            async with self._session.get(url, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return _fail(f"{resp.status} {text}")
                return _ok(truncate_payload(text))
        except TimeoutError as exc:
            return _fail(str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return _fail(str(exc))

    async def logs(self, name: str, tail: int = 100) -> Observation:
        url = _engine_url(f"/containers/{_container_segment(name)}/logs")
        params: dict[str, str] = {
            "stdout": "1",
            "stderr": "1",
            "tail": str(tail),
        }
        timeout = _timeout()
        try:
            async with self._session.get(url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return _fail(f"{resp.status} {text}")
                raw = await resp.read()
                return _ok(truncate_payload(_logs_text(raw)))
        except TimeoutError as exc:
            return _fail(str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return _fail(str(exc))

    async def restart(self, name: str) -> Observation:
        if name not in RESTART_ALLOWLIST or name in NEVER_RESTART:
            return _fail(f"{name} is not on the restart allowlist")
        url = _engine_url(f"/containers/{_container_segment(name)}/restart")
        timeout = _timeout()
        try:
            async with self._session.post(url, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status not in (200, 204):
                    return _fail(f"{resp.status} {text}")
                return _ok(text)
        except TimeoutError as exc:
            return _fail(str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return _fail(str(exc))
