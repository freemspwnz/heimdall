from typing import Self


def _formatted(message: str, args: tuple[object, ...]) -> str:
    return message.format(*args) if args else message


class SilentLogger:
    def trace(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def success(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def critical(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def log(self, level: str, message: str, *args: object, **kwargs: object) -> None:
        return None

    def bind(self, **kwargs: object) -> Self:
        return self


class RecordingLogger(SilentLogger):
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.debug_lines: list[str] = []

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        self.debug_lines.append(_formatted(message, args))

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        self.lines.append(_formatted(message, args))

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self.lines.append(_formatted(message, args))
