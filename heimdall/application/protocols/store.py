from typing import Protocol

from heimdall.domain.models import Chunk

from .embedder import Embedder


class VectorStore(Protocol):
    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None: ...

    async def list_chunks(self) -> list[Chunk]: ...

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = 5,
    ) -> list[Chunk]: ...
