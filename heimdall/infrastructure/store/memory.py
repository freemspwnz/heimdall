import math

from heimdall.application.protocols import Embedder
from heimdall.domain.models import Chunk

from ..constants import RETRIEVE_TOP_K


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[tuple[Chunk, list[float]]] = []

    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None:
        if not chunks:
            self._items = []
            return
        vectors = await embedder.embed([chunk.text for chunk in chunks])
        self._items = list(zip(chunks, vectors, strict=True))

    async def list_chunks(self) -> list[Chunk]:
        return [chunk for chunk, _vector in self._items]

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]:
        if not self._items:
            return []
        query_vector = (await embedder.embed([query], query=True))[0]
        scored: list[tuple[float, int, Chunk]] = [
            (self._cosine_similarity(query_vector, vector), index, chunk)
            for index, (chunk, vector) in enumerate(self._items)
        ]
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return [chunk for _, _, chunk in scored[:k]]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for a, b in zip(left, right, strict=True):
            dot += a * b
            norm_a += a * a
            norm_b += b * b
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
