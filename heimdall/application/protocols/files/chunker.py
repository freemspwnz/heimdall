from typing import Protocol

from heimdall.domain.models import Chunk


class Chunker(Protocol):
    def __call__(self, text: str, source: str) -> list[Chunk]: ...
