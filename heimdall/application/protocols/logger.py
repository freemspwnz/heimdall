from typing import Protocol, Self, runtime_checkable


@runtime_checkable
class Logger(Protocol):
    """Protocol for logging system."""

    def trace(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at TRACE level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at DEBUG level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at INFO level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def success(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at SUCCESS level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at WARNING level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at ERROR level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def critical(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at ERROR level with mandatory traceback inclusion.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at EXCEPTION level.

        Args:
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def log(self, level: str, message: str, *args: object, **kwargs: object) -> None:
        """Log a message at the specified level.

        Args:
            level: Logging level.
            message: Log message (may contain {} placeholders).
            *args: Format arguments for the message.
            **kwargs: Extra logging context.
        """
        ...

    def bind(self, **kwargs: object) -> Self:
        """Create a new logger instance with bound context.

        Args:
            **kwargs: Contextual data for binding to all subsequent logs.

        Returns:
            New Logger instance with updated context.
        """
        ...
