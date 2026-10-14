from typing import Protocol

from heimdall.domain.models import Action


class UserChannel(Protocol):
    def emit(self, text: str) -> None: ...

    def confirm(self, action: Action) -> bool: ...
