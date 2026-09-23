from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import aiohttp

from heimdall.channels.cli import POSITIVE_ANSWERS, PROMPT
from heimdall.client.session import AgentClient
from heimdall.models import Action

AGENT_UNAVAILABLE = "агент не запущен, запустите heimdall serve"
REPL_PROMPT = "heimdall> "
REPL_EXIT_WORDS = frozenset({"exit", "quit"})

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


async def run_repl(
    base_url: str,
    input_fn: InputFn = _default_input,
    confirm_fn: InputFn | None = None,
    output_fn: Callable[[str], None] = _default_output,
) -> int:
    read_confirm = confirm_fn if confirm_fn is not None else _default_confirm
    try:
        async with aiohttp.ClientSession() as http:
            client = AgentClient(base_url, http=http)
            while True:
                raw = input_fn()
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
                            decision = _decision_from_answer(read_confirm())
                            if event.run_id is None:
                                output_fn("missing run_id for hitl")
                                return 1
                            await client.resume(event.run_id, decision)
                        elif event.type in {"report", "error", "busy"}:
                            if event.text:
                                output_fn(event.text)
                except (
                    aiohttp.ClientConnectorError,
                    aiohttp.ClientOSError,
                    aiohttp.ServerDisconnectedError,
                    OSError,
                ):
                    output_fn(AGENT_UNAVAILABLE)
                    return 1
    except (
        aiohttp.ClientConnectorError,
        aiohttp.ClientOSError,
        aiohttp.ServerDisconnectedError,
        OSError,
    ):
        output_fn(AGENT_UNAVAILABLE)
        return 1
