from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from heimdall.constants import MAX_OBSERVATION_LINES
from heimdall.graph.nodes import _tail
from heimdall.providers import FakeEmbedder
from heimdall.rag.store import PgVectorStore


def test_tail_clamps_to_observation_limit() -> None:
    assert _tail(10_000) == MAX_OBSERVATION_LINES
    assert _tail("500") == MAX_OBSERVATION_LINES


def test_tail_clamps_non_positive_to_one() -> None:
    assert _tail(0) == 1
    assert _tail(-5) == 1


def test_tail_accepts_valid_int() -> None:
    assert _tail(25) == 25
    assert _tail("40") == 40


@pytest.mark.asyncio
async def test_pg_empty_upsert_deletes_existing_rows() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.close = AsyncMock()
    conn.transaction = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    with patch("heimdall.rag.store.asyncpg.connect", AsyncMock(return_value=conn)):
        store = PgVectorStore("postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall")
        await store.upsert([], FakeEmbedder())

    conn.execute.assert_awaited()
    sql = conn.execute.await_args.args[0]
    assert "DELETE FROM chunks" in sql
    conn.close.assert_awaited()


@pytest.mark.asyncio
async def test_pg_empty_upsert_ignores_missing_table() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=asyncpg.UndefinedTableError("chunks"))
    conn.close = AsyncMock()

    with patch("heimdall.rag.store.asyncpg.connect", AsyncMock(return_value=conn)):
        store = PgVectorStore("postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall")
        await store.upsert([], FakeEmbedder())

    conn.close.assert_awaited()
