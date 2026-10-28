import asyncpg

from heimdall.application.protocols import Embedder
from heimdall.domain.models import Chunk

from ..constants import RETRIEVE_TOP_K


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
        await self.ensure_schema()
        if not chunks:
            conn = await asyncpg.connect(self._dsn)
            try:
                try:
                    await conn.execute("DELETE FROM chunks")
                except asyncpg.UndefinedTableError:
                    return
            finally:
                await conn.close()
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
            async with conn.transaction():
                await conn.execute("DELETE FROM chunks")
                await conn.executemany(
                    "INSERT INTO chunks (source, body, embedding)"
                    " VALUES ($1, $2, $3::vector)",
                    [
                        (chunk.source, chunk.text, self._vector_literal(vector))
                        for chunk, vector in zip(chunks, vectors, strict=True)
                    ],
                )
        finally:
            await conn.close()

    async def list_chunks(self) -> list[Chunk]:
        conn = await asyncpg.connect(self._dsn)
        try:
            rows = await conn.fetch("SELECT source, body FROM chunks ORDER BY id")
        finally:
            await conn.close()
        return [Chunk(text=row["body"], source=row["source"]) for row in rows]

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]:
        query_vector = (await embedder.embed([query], query=True))[0]
        conn = await asyncpg.connect(self._dsn)
        try:
            rows = await conn.fetch(
                "SELECT source, body FROM chunks "
                "ORDER BY embedding <=> $1::vector LIMIT $2",
                self._vector_literal(query_vector),
                k,
            )
        finally:
            await conn.close()
        return [Chunk(text=row["body"], source=row["source"]) for row in rows]

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(str(value) for value in vector) + "]"
