from __future__ import annotations

import sys
from typing import TextIO

from heimdall.models import Action

POSITIVE_ANSWERS = frozenset({"y", "yes"})
PROMPT = "Выполнить? [y/N]: "


class CliChannel:
    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self._stdin = stdin if stdin is not None else sys.stdin
        self._stdout = stdout if stdout is not None else sys.stdout

    def emit(self, text: str) -> None:
        print(text, file=self._stdout)

    def confirm(self, action: Action) -> bool:
        self.emit(f"Команда: docker restart {action.target}")
        self.emit(f"Причина: {action.reason}")
        self.emit(f"Риск: {action.risk}")
        self._stdout.write(PROMPT)
        self._stdout.flush()
        answer = self._stdin.readline()
        return answer.strip().lower() in POSITIVE_ANSWERS
