from __future__ import annotations

import math
from typing import Protocol

import asyncpg

from heimdall.constants import RETRIEVE_TOP_K
from heimdall.models import Chunk
from heimdall.providers.protocols import Embedder


class VectorStore(Protocol):
    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None: ...

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[tuple[Chunk, list[float]]] = []

    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None:
        if not chunks:
            return
        vectors = await embedder.embed([chunk.text for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._items.append((chunk, vector))

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]:
        if not self._items:
            return []
        query_vector = (await embedder.embed([query]))[0]
        scored: list[tuple[float, int, Chunk]] = [
            (_cosine_similarity(query_vector, vector), index, chunk)
            for index, (chunk, vector) in enumerate(self._items)
        ]
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return [chunk for _, _, chunk in scored[:k]]


class PgVectorStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def ensure_schema(self) -> None:
        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        finally:
            await conn.close()

    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None:
        if not chunks:
            return
        vectors = await embedder.embed([chunk.text for chunk in chunks])
        dimension = len(vectors[0])
        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS chunks ("
                "id bigserial, "
                "source text, "
                "body text, "
                f"embedding vector({dimension})"
                ")"
            )
            await conn.execute("DELETE FROM chunks")
            await conn.executemany(
                "INSERT INTO chunks (source, body, embedding)"
                " VALUES ($1, $2, $3::vector)",
                [
                    (chunk.source, chunk.text, _vector_literal(vector))
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ],
            )
        finally:
            await conn.close()

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]:
        query_vector = (await embedder.embed([query]))[0]
        conn = await asyncpg.connect(self._dsn)
        try:
            rows = await conn.fetch(
                "SELECT source, body FROM chunks "
                "ORDER BY embedding <=> $1::vector LIMIT $2",
                _vector_literal(query_vector),
                k,
            )
        finally:
            await conn.close()
        return [Chunk(text=row["body"], source=row["source"]) for row in rows]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"


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
