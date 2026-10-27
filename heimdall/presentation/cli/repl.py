import asyncio
from collections.abc import Awaitable, Callable

import aiohttp

from heimdall.application.exceptions import IngestError
from heimdall.domain.models import Action
from heimdall.infrastructure.aiohttp import AgentClient

AGENT_UNAVAILABLE = "агент не запущен, запустите python -m heimdall serve"
ASK_FAILED = "не удалось выполнить запрос"
INGEST_FAILED = "не удалось загрузить данные"
INGESTED = "Проиндексировано фрагментов"
REPL_PROMPT = "heimdall> "
REPL_EXIT_WORDS = frozenset({"exit", "quit"})
POSITIVE_ANSWERS = frozenset({"y", "yes"})
PROMPT = "Выполнить? [y/N]: "
INGEST_WORDS = frozenset({"ingest", "ingest-data", "reload"})

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


def _decision_from_answer(answer: str | None) -> bool:
    return answer is not None and answer.strip().lower() in POSITIVE_ANSWERS


async def _read_stdin(fn: InputFn) -> str | None:
    # Keep the event loop alive: sync input() otherwise freezes aiohttp
    # (lab: second ask → ClientConnectorError while serve is up).
    return await asyncio.to_thread(fn)


_CLIENT_ERRORS = (
    TimeoutError,
    aiohttp.ClientConnectorError,
    aiohttp.ClientOSError,
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientPayloadError,
    aiohttp.ClientResponseError,
    OSError,
)


async def _guard(
    action: Callable[[], Awaitable[object]],
    output_fn: Callable[[str], None],
    message: str,
) -> bool:
    try:
        await action()
        return True
    except _CLIENT_ERRORS as exc:
        output_fn(f"{message}: {type(exc).__name__}: {exc}")
        return False


async def run_repl(
    client: AgentClient,
    input_fn: InputFn = _default_input,
    confirm_fn: InputFn = _default_confirm,
    output_fn: Callable[[str], None] = _default_output,
) -> int:
    if not await _guard(client.probe, output_fn, AGENT_UNAVAILABLE):
        return 1

    while True:
        raw = await _read_stdin(input_fn)
        if raw is None:
            return 0
        question = raw.strip()
        if not question:
            continue
        if question.lower() in REPL_EXIT_WORDS:
            return 0
        if question.lower() in INGEST_WORDS:
            try:
                count = await client.ingest()
            except IngestError as exc:
                output_fn(f"{INGEST_FAILED}: {exc}")
            except _CLIENT_ERRORS as exc:
                output_fn(f"{INGEST_FAILED}: {type(exc).__name__}: {exc}")
            else:
                output_fn(f"{INGESTED}: {count}")
            continue

        async def ask(current: str = question) -> None:
            async for event in client.ask(current):
                if event.type == "status":
                    if event.text:
                        output_fn(event.text)
                elif event.type == "hitl":
                    if event.action is not None:
                        for line in _format_action(event.action):
                            output_fn(line)
                    decision = _decision_from_answer(await _read_stdin(confirm_fn))
                    if event.run_id is None:
                        output_fn("missing run_id for hitl")
                        continue
                    await client.resume(event.run_id, decision)
                elif event.type in {"report", "error", "busy"}:
                    if event.text:
                        output_fn(event.text)

        await _guard(ask, output_fn, ASK_FAILED)
