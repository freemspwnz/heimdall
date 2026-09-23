from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal
from urllib.parse import urljoin

import aiohttp

from heimdall.channels.cli import POSITIVE_ANSWERS, PROMPT
from heimdall.client.session import AgentClient, make_client_session
from heimdall.models import Action

AGENT_UNAVAILABLE = "агент не запущен, запустите heimdall serve"
ASK_FAILED = "не удалось выполнить запрос"
REPL_PROMPT = "heimdall> "
REPL_EXIT_WORDS = frozenset({"exit", "quit"})

_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5, sock_connect=5)

InputFn = Callable[[], str | None]


def _default_input() -> str | None:
    try:
        return input(REPL_PROMPT)
    except EOFError:
        return None


def _default_confirm() -> str | None:
    try:
        return input(PROMPT)
    except EOFError:
        return None


def _default_output(text: str) -> None:
    print(text)


def _format_action(action: Action) -> list[str]:
    return [
        f"Команда: docker restart {action.target}",
        f"Причина: {action.reason}",
        f"Риск: {action.risk}",
    ]


def _decision_from_answer(answer: str | None) -> Literal["yes", "no"]:
    if answer is not None and answer.strip().lower() in POSITIVE_ANSWERS:
        return "yes"
    return "no"


async def _read_stdin(fn: InputFn) -> str | None:
    # Keep the event loop alive: sync input() otherwise freezes aiohttp
    # (lab: second ask → ClientConnectorError while serve is up).
    return await asyncio.to_thread(fn)


async def _probe_agent(http: aiohttp.ClientSession, base_url: str) -> None:
    url = urljoin(base_url.rstrip("/") + "/", "health")
    async with http.get(url, timeout=_PROBE_TIMEOUT) as resp:
        resp.raise_for_status()


async def run_repl(
    base_url: str,
    input_fn: InputFn = _default_input,
    confirm_fn: InputFn | None = None,
    output_fn: Callable[[str], None] = _default_output,
) -> int:
    read_confirm = confirm_fn if confirm_fn is not None else _default_confirm
    try:
        async with make_client_session() as http:
            try:
                await _probe_agent(http, base_url)
            except (
                TimeoutError,
                aiohttp.ClientConnectorError,
                aiohttp.ClientOSError,
                aiohttp.ServerDisconnectedError,
                aiohttp.ClientResponseError,
                OSError,
            ):
                output_fn(AGENT_UNAVAILABLE)
                return 1

            client = AgentClient(base_url, http=http)
            while True:
                raw = await _read_stdin(input_fn)
                if raw is None:
                    return 0
                question = raw.strip()
                if not question:
                    continue
                if question.lower() in REPL_EXIT_WORDS:
                    return 0
                try:
                    async for event in client.ask(question):
                        if event.type == "status":
                            if event.text:
                                output_fn(event.text)
                        elif event.type == "hitl":
                            if event.action is not None:
                                for line in _format_action(event.action):
                                    output_fn(line)
                            decision = _decision_from_answer(
                                await _read_stdin(read_confirm)
                            )
                            if event.run_id is None:
                                output_fn("missing run_id for hitl")
                                continue
                            await client.resume(event.run_id, decision)
                        elif event.type in {"report", "error", "busy"}:
                            if event.text:
                                output_fn(event.text)
                except (
                    TimeoutError,
                    aiohttp.ClientConnectorError,
                    aiohttp.ClientOSError,
                    aiohttp.ServerDisconnectedError,
                    aiohttp.ClientPayloadError,
                    aiohttp.ClientResponseError,
                    OSError,
                ) as exc:
                    output_fn(f"{ASK_FAILED}: {type(exc).__name__}: {exc}")
                    continue
    except aiohttp.ClientConnectorError:
        output_fn(AGENT_UNAVAILABLE)
        return 1
