import logging
from typing import Any

from loguru import logger

# Global variables used for masking
_MASKED_VALUE = "****"
_SENSITIVE_KEYWORDS: set[str] = {
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "authorization",
    "bearer",
    "access_token",
    "refresh_token",
    "apikey",
    "cookie",
    "set-cookie",
    "client_secret",
    "private_key",
    "secret_key",
}


Scrubbable = str | dict[Any, Any] | list[Any] | tuple[Any, ...] | set[Any]


def scrub(
    obj: Scrubbable,
    secrets: list[str] | None = None,
) -> Scrubbable:
    """Recursively scrub data and mask known secrets."""
    if isinstance(obj, str):
        if secrets:
            for s in secrets:
                if s:
                    obj = obj.replace(s, _MASKED_VALUE)
        return obj

    if isinstance(obj, dict):
        return {
            k: (
                _MASKED_VALUE
                if any(w in str(k).lower() for w in _SENSITIVE_KEYWORDS)
                else scrub(v, secrets)
            )
            for k, v in obj.items()
        }

    if isinstance(obj, list | tuple | set):
        return type(obj)([scrub(i, secrets) for i in obj])

    return obj


class LoguruHandler(logging.Handler):
    """Adapter that bridges stdlib logging to Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Resolve Loguru level when available
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find the stack frame that originated the log record
        frame, depth = logging.currentframe(), 2
        if frame is not None:
            while frame.f_code.co_filename == logging.__file__:
                parent = frame.f_back
                if parent is None:
                    break
                frame = parent
                depth += 1

        # Forward to Loguru while preserving the library logger name
        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
            logger_name=record.name,
        )
