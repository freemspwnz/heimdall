import pytest
from heimdall.providers import FakeEmbedder
from heimdall.rag import InMemoryVectorStore, chunk_markdown

POSTGRES_QUERY = "Что с postgres?"  # noqa: RUF001

inventory = """# Inventory

## Postgres

Postgres runs on the homelab host with exporter metrics.

## Traefik

Traefik reverse proxy.
"""

pg_runbook = """# Postgres

## Symptoms

Postgres connections fail and the exporter is down.

## Restart

Restart postgres after checking logs.
"""

jelly = """# Jellyfin

## Media

Jellyfin streams movies. Do not mention databases here.
"""


@pytest.mark.asyncio
async def test_empty_store_search_returns_empty_list() -> None:
    store = InMemoryVectorStore()
    hits = await store.search(POSTGRES_QUERY, FakeEmbedder())
    assert hits == []


@pytest.mark.asyncio
async def test_postgres_question_retrieves_postgres_not_jellyfin() -> None:
    store = InMemoryVectorStore()
    embedder = FakeEmbedder()
    await store.upsert(
        chunk_markdown(inventory, "inventory.md")
        + chunk_markdown(pg_runbook, "postgres.md")
        + chunk_markdown(jelly, "jellyfin.md"),
        embedder,
    )
    hits = await store.search(POSTGRES_QUERY, embedder, k=5)
    blob = " ".join(h.text.lower() + h.source for h in hits)
    assert "postgres" in blob
    first_source = hits[0].source
    assert "jellyfin" not in blob.split("postgres")[0] or first_source != "jellyfin.md"
    assert any("postgres" in h.source or "postgres" in h.text.lower() for h in hits)
    assert hits[0].source in {"postgres.md", "inventory.md"}
    assert hits[0].source != "jellyfin.md"
