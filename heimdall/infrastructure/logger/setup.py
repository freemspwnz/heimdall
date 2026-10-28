import asyncio
import logging
import sys
from importlib.metadata import version
from types import TracebackType
from typing import Any

from loguru import logger

from .formatters import LoguruHandler, scrub


def _sys_exception_handler(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.opt(exception=(exc_type, exc_value, exc_traceback)).critical(
        "Uncaught exception"
    )


def _asyncio_exception_handler(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, object],
) -> None:
    msg = context.get("message", "")
    exc = context.get("exception")
    if isinstance(exc, BaseException):
        logger.opt(exception=exc).error("asyncio: {}", msg)
    else:
        logger.error("asyncio: {} | context={}", msg, context)


_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
    "{extra[app]} | {name}:{function}:{line} | {message}"
)
_NOISY_LIBS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "aiohttp",
    "asyncio",
)
_APP = "heimdall"


def setup_logging(secrets: list[str], *, level: str) -> None:
    def patch_record(record: Any) -> None:
        record["message"] = scrub(record["message"], secrets=secrets)
        record["extra"] = scrub(record["extra"], secrets=secrets)

    ver = version("heimdall")
    logger.remove()
    logger.configure(
        patcher=patch_record,
        extra={"app": _APP, "ver": ver},
    )
    logger.add(sys.stdout, level=level, serialize=False, format=_FORMAT)

    sys.excepthook = _sys_exception_handler
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.set_exception_handler(_asyncio_exception_handler)

    logging.basicConfig(handlers=[LoguruHandler()], level=logging.NOTSET, force=True)
    for name in _NOISY_LIBS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger.info("Logging configured level={} version={}", level, ver)
