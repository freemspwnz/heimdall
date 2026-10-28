import json
from urllib.parse import quote

import aiohttp

from heimdall.domain.models import Observation

from ..constants import NEVER_RESTART
from .utils import fail, ok, timeout, truncate_payload

_SOURCE = "docker"
_ENGINE_BASE = "http://localhost"
_STATE_KEYS = (
    "Status",
    "Running",
    "Restarting",
    "OOMKilled",
    "Dead",
    "ExitCode",
    "Error",
    "StartedAt",
    "FinishedAt",
)


class DockerClient:
    def __init__(self, docker_host: str, session: aiohttp.ClientSession) -> None:
        self._docker_host = docker_host
        self._session = session

    async def ps(self) -> Observation:
        url = self._engine_url("/containers/json")
        params: dict[str, str] = {"all": "1"}
        try:
            async with self._session.get(url, params=params, timeout=timeout()) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return fail(_SOURCE, f"{resp.status} {truncate_payload(text)}")
                try:
                    parsed: object = json.loads(text)
                except json.JSONDecodeError as exc:
                    return fail(_SOURCE, str(exc))
                if not isinstance(parsed, list):
                    return fail(_SOURCE, "unexpected docker ps payload")
                lines: list[str] = []
                for item in parsed:
                    line = self._format_ps_line(item)
                    if line is not None:
                        lines.append(line)
                return ok(_SOURCE, truncate_payload("\n".join(lines)))
        except TimeoutError as exc:
            return fail(_SOURCE, str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return fail(_SOURCE, str(exc))

    async def inspect(self, name: str) -> Observation:
        url = self._engine_url(f"/containers/{self._container_segment(name)}/json")
        try:
            async with self._session.get(url, timeout=timeout()) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return fail(_SOURCE, f"{resp.status} {truncate_payload(text)}")
                try:
                    parsed: object = json.loads(text)
                except json.JSONDecodeError:
                    return ok(_SOURCE, truncate_payload(text))
                if isinstance(parsed, dict):
                    return ok(_SOURCE, self._slim_inspect(parsed))
                return ok(_SOURCE, truncate_payload(text))
        except TimeoutError as exc:
            return fail(_SOURCE, str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return fail(_SOURCE, str(exc))

    async def logs(self, name: str, tail: int = 100) -> Observation:
        url = self._engine_url(f"/containers/{self._container_segment(name)}/logs")
        params: dict[str, str] = {
            "stdout": "1",
            "stderr": "1",
            "tail": str(tail),
        }
        try:
            async with self._session.get(url, params=params, timeout=timeout()) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return fail(_SOURCE, f"{resp.status} {truncate_payload(text)}")
                raw = await resp.read()
                return ok(_SOURCE, truncate_payload(self._logs_text(raw)))
        except TimeoutError as exc:
            return fail(_SOURCE, str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return fail(_SOURCE, str(exc))

    async def restart(self, name: str) -> Observation:
        if not name or name in NEVER_RESTART:
            return fail(_SOURCE, f"{name} restart is forbidden")
        url = self._engine_url(f"/containers/{self._container_segment(name)}/restart")
        try:
            async with self._session.post(url, timeout=timeout()) as resp:
                text = await resp.text()
                if resp.status not in (200, 204):
                    return fail(_SOURCE, f"{resp.status} {truncate_payload(text)}")
                return ok(_SOURCE, text)
        except TimeoutError as exc:
            return fail(_SOURCE, str(exc) or "timeout")
        except aiohttp.ClientError as exc:
            return fail(_SOURCE, str(exc))

    @staticmethod
    def _slim_inspect(parsed: dict[str, object]) -> str:
        state = parsed.get("State")
        slim_state: dict[str, object] = {}
        if isinstance(state, dict):
            for key in _STATE_KEYS:
                if key in state:
                    slim_state[key] = state[key]
            health = state.get("Health")
            if isinstance(health, dict) and isinstance(health.get("Status"), str):
                slim_state["Health"] = {"Status": health["Status"]}
        body: dict[str, object] = {"Name": parsed.get("Name"), "State": slim_state}
        restart = parsed.get("RestartCount")
        if isinstance(restart, int) and not isinstance(restart, bool):
            body["RestartCount"] = restart
        return json.dumps(body, ensure_ascii=False)

    @staticmethod
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

    @staticmethod
    def _looks_multiplexed(raw: bytes) -> bool:
        if len(raw) < 8:
            return False
        if raw[0] not in (1, 2):
            return False
        if raw[1:4] != b"\x00\x00\x00":
            return False
        size = int.from_bytes(raw[4:8], "big")
        return 8 + size <= len(raw)

    @staticmethod
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

    def _logs_text(self, raw: bytes) -> str:
        if self._looks_multiplexed(raw):
            return self._demux_logs(raw)
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _engine_url(path: str) -> str:
        return f"{_ENGINE_BASE}{path}"

    @staticmethod
    def _container_segment(name: str) -> str:
        return quote(name, safe="")
