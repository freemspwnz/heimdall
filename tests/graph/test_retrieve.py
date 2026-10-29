import asyncio
from pathlib import Path
from typing import cast

import pytest
from heimdall.application.exceptions import EmbeddingsUnavailable
from heimdall.application.protocols import Embedder
from heimdall.domain.models import Chunk
from heimdall.infrastructure.embedders import FakeEmbedder
from heimdall.infrastructure.graph.nodes.retrieve import retrieve
from heimdall.infrastructure.graph.state import GraphState
from heimdall.infrastructure.store import InMemoryVectorStore
from tests.support import RecordingLogger, SilentLogger

QUESTION = "что с alpha?"  # noqa: RUF001


class RecordingStore(InMemoryVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.searches = 0

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = 5,
    ) -> list[Chunk]:
        self.searches += 1
        return await super().search(query, embedder, k=k)


class DownEmbedder:
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del texts, query
        raise EmbeddingsUnavailable("down")


class BoomEmbedder:
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del texts, query
        raise RuntimeError("boom")


class CancelSearch(InMemoryVectorStore):
    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = 5,
    ) -> list[Chunk]:
        del query, embedder, k
        raise asyncio.CancelledError()


def _patch(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        "heimdall.infrastructure.graph.paths.RUNBOOKS_DIR",
        root,
    )


def _state(runbooks: object | None = None, *, omit: bool = False) -> GraphState:
    state: dict[str, object] = {"question": QUESTION}
    if not omit:
        state["runbooks"] = [] if runbooks is None else runbooks
    return cast(GraphState, state)


async def _stored() -> RecordingStore:
    store = RecordingStore()
    await store.upsert(
        [Chunk(text="from store", source="runbooks/store.md")],
        FakeEmbedder(),
    )
    return store


@pytest.mark.asyncio
async def test_reads_files_in_order_without_search(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    (tmp_path / "delta.md").write_text("delta body", encoding="utf-8")
    (tmp_path / "alpha.md").write_text("alpha body", encoding="utf-8")
    store = await _stored()
    update = await retrieve(store, FakeEmbedder(), SilentLogger())(
        _state(["delta.md", "alpha.md"])
    )
    assert store.searches == 0
    assert update["retrieved_chunks"] == [
        {"text": "delta body", "source": "runbooks/delta.md"},
        {"text": "alpha body", "source": "runbooks/alpha.md"},
    ]


@pytest.mark.asyncio
async def test_bad_name_and_missing_file_keep_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    (tmp_path / "alpha.md").write_text("alpha body", encoding="utf-8")
    store = await _stored()
    update = await retrieve(store, FakeEmbedder(), SilentLogger())(
        _state(
            [
                "../inventory.md",
                "alpha.md",
                "missing.md",
                "alpha.md",
                1,
                "runbooks/alpha.md",
            ]
        )
    )
    assert store.searches == 0
    assert update["retrieved_chunks"] == [
        {"text": "alpha body", "source": "runbooks/alpha.md"},
    ]


@pytest.mark.asyncio
async def test_empty_file_counts_as_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    store = await _stored()
    update = await retrieve(store, FakeEmbedder(), SilentLogger())(_state(["empty.md"]))
    assert store.searches == 0
    assert update["retrieved_chunks"] == [
        {"text": "", "source": "runbooks/empty.md"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("runbooks", [[], ["missing.md"]])
async def test_no_loaded_file_searches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runbooks: list[str],
) -> None:
    _patch(monkeypatch, tmp_path)
    store = await _stored()
    update = await retrieve(store, FakeEmbedder(), SilentLogger())(_state(runbooks))
    assert store.searches == 1
    assert update["retrieved_chunks"] == [
        {"text": "from store", "source": "runbooks/store.md"},
    ]


@pytest.mark.asyncio
async def test_missing_key_searches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    store = await _stored()
    update = await retrieve(store, FakeEmbedder(), SilentLogger())(_state(omit=True))
    assert store.searches == 1
    assert update["retrieved_chunks"] == [
        {"text": "from store", "source": "runbooks/store.md"},
    ]


@pytest.mark.asyncio
async def test_embeddings_down_on_search_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    store = await _stored()
    update = await retrieve(store, DownEmbedder(), SilentLogger())(_state([]))
    assert update["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_loaded_file_does_not_need_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    (tmp_path / "alpha.md").write_text("alpha body", encoding="utf-8")
    store = RecordingStore()
    update = await retrieve(store, DownEmbedder(), SilentLogger())(_state(["alpha.md"]))
    assert store.searches == 0
    assert update["retrieved_chunks"] == [
        {"text": "alpha body", "source": "runbooks/alpha.md"},
    ]


@pytest.mark.asyncio
async def test_search_runtime_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    store = await _stored()
    with pytest.raises(RuntimeError, match="boom"):
        await retrieve(store, BoomEmbedder(), SilentLogger())(_state([]))


@pytest.mark.asyncio
async def test_cancelled_search_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    with pytest.raises(asyncio.CancelledError):
        await retrieve(CancelSearch(), FakeEmbedder(), SilentLogger())(_state([]))


@pytest.mark.asyncio
async def test_retrieve_logs_question_and_source_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch(monkeypatch, tmp_path)
    (tmp_path / "alpha.md").write_text("alpha body", encoding="utf-8")
    recorded = RecordingLogger()
    await retrieve(RecordingStore(), FakeEmbedder(), recorded)(_state(["alpha.md"]))
    assert recorded.lines == [
        "question что с alpha?",  # noqa: RUF001
        "sources=runbooks/alpha.md",
    ]
