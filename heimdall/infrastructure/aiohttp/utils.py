import aiohttp

from heimdall.domain.models import Observation

from ..constants import HTTP_TIMEOUT_SECONDS


def truncate_payload(text: str, max_lines: int = 100, max_chars: int = 4000) -> str:
    lines = text.splitlines()
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines])
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def timeout(total: int | None = HTTP_TIMEOUT_SECONDS) -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=total)


def fail(source: str, error: str) -> Observation:
    return Observation(source=source, ok=False, payload="", error=error)


def ok(source: str, payload: str) -> Observation:
    return Observation(source=source, ok=True, payload=payload)
