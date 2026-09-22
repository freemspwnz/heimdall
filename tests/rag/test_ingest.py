from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from heimdall.models import Chunk
from heimdall.providers.fake import KEYWORDS, FakeEmbedder
from heimdall.providers.protocols import EmbeddingsUnavailable
from heimdall.rag.ingest import ingest_knowledge
from heimdall.rag.store import InMemoryVectorStore, PgVectorStore

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "docs" / "knowledge"
TUNNEL_QUERY = "Почему отвалился туннель"
DSN = "postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall"


class _UnavailableEmbedder:
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del texts, query
        raise EmbeddingsUnavailable("embeddings down")


class _NoopTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


def _pg_connection() -> AsyncMock:
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.close = AsyncMock()
    conn.transaction = MagicMock(return_value=_NoopTransaction())
    return conn


@pytest.mark.asyncio
async def test_ingest_knowledge_retrieves_tunnel_runbook() -> None:
    store = InMemoryVectorStore()
    embedder = FakeEmbedder()
    count = await ingest_knowledge(KNOWLEDGE_DIR, store, embedder)
    assert count > 0
    hits = await store.search(TUNNEL_QUERY, embedder)
    blob = " ".join(hit.text for hit in hits)
    assert "sing-box" in blob or "3x-ui" in blob


@pytest.mark.asyncio
async def test_ingest_knowledge_propagates_embeddings_unavailable() -> None:
    store = InMemoryVectorStore()
    with pytest.raises(EmbeddingsUnavailable):
        await ingest_knowledge(KNOWLEDGE_DIR, store, _UnavailableEmbedder())


@pytest.mark.asyncio
async def test_pgvector_ensure_schema_creates_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _pg_connection()
    connect = AsyncMock(return_value=conn)
    monkeypatch.setattr("heimdall.rag.store.asyncpg.connect", connect)
    store = PgVectorStore(DSN)
    await store.ensure_schema()
    connect.assert_awaited_once_with(DSN)
    executed = " ".join(call.args[0] for call in conn.execute.await_args_list)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed


@pytest.mark.asyncio
async def test_pgvector_upsert_replaces_all_and_sizes_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _pg_connection()
    connect = AsyncMock(return_value=conn)
    monkeypatch.setattr("heimdall.rag.store.asyncpg.connect", connect)
    store = PgVectorStore(DSN)
    chunks = [Chunk(text="tunnel body", source="runbooks/tunnel.md")]
    await store.upsert(chunks, FakeEmbedder())
    sqls = [call.args[0] for call in conn.execute.await_args_list]
    create = next(sql for sql in sqls if "CREATE TABLE" in sql)
    assert "body text" in create
    assert f"vector({len(KEYWORDS)})" in create.replace(" ", "")
    delete_index = next(i for i, sql in enumerate(sqls) if "DELETE FROM chunks" in sql)
    assert conn.executemany.await_count == 1
    insert_sql = conn.executemany.await_args.args[0]
    assert "INSERT INTO chunks" in insert_sql
    rows = conn.executemany.await_args.args[1]
    assert rows[0][0] == "runbooks/tunnel.md"
    assert rows[0][1] == "tunnel body"
    assert delete_index < len(sqls)


@pytest.mark.asyncio
async def test_pgvector_upsert_delete_and_insert_run_in_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _pg_connection()
    in_transaction = False
    ops_in_transaction: list[str] = []

    class _Transaction:
        async def __aenter__(self) -> None:
            nonlocal in_transaction
            in_transaction = True

        async def __aexit__(self, *args: object) -> None:
            nonlocal in_transaction
            in_transaction = False

    async def execute(sql: str, *args: object) -> None:
        if in_transaction:
            ops_in_transaction.append(sql)

    async def executemany(sql: str, *args: object) -> None:
        if in_transaction:
            ops_in_transaction.append(sql)

    conn.transaction = MagicMock(return_value=_Transaction())
    conn.execute = AsyncMock(side_effect=execute)
    conn.executemany = AsyncMock(side_effect=executemany)
    connect = AsyncMock(return_value=conn)
    monkeypatch.setattr("heimdall.rag.store.asyncpg.connect", connect)
    store = PgVectorStore(DSN)
    await store.upsert(
        [Chunk(text="tunnel body", source="runbooks/tunnel.md")],
        FakeEmbedder(),
    )
    conn.transaction.assert_called_once_with()
    assert any("DELETE FROM chunks" in sql for sql in ops_in_transaction)
    assert any("INSERT INTO chunks" in sql for sql in ops_in_transaction)


@pytest.mark.asyncio
async def test_pgvector_search_uses_cosine_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _pg_connection()
    row = MagicMock()
    row.__getitem__.side_effect = lambda key: {
        "source": "runbooks/tunnel.md",
        "body": "sing-box restart",
    }[key]
    conn.fetch = AsyncMock(return_value=[row])
    connect = AsyncMock(return_value=conn)
    monkeypatch.setattr("heimdall.rag.store.asyncpg.connect", connect)
    store = PgVectorStore(DSN)
    hits = await store.search(TUNNEL_QUERY, FakeEmbedder(), k=3)
    assert hits == [Chunk(text="sing-box restart", source="runbooks/tunnel.md")]
    fetch_sql = conn.fetch.await_args.args[0]
    assert "<=>" in fetch_sql
    assert conn.fetch.await_args.args[2] == 3
