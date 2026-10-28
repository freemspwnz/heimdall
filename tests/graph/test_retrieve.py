import asyncio
import json
from typing import cast

import pytest
from heimdall.application.exceptions import ChatUnavailable, EmbeddingsUnavailable
from heimdall.application.models import ChatMessage, ChatResult, ToolSpec
from heimdall.application.protocols import Embedder
from heimdall.domain.models import Chunk
from heimdall.infrastructure.constants import RETRIEVE_TOP_K
from heimdall.infrastructure.embedders import FakeEmbedder
from heimdall.infrastructure.graph.nodes.retrieve import retrieve
from heimdall.infrastructure.graph.prompts import ROUTER_SYSTEM
from heimdall.infrastructure.graph.state import GraphState, StateUpdate
from heimdall.infrastructure.llms import FakeChatModel, ScriptedTurn
from heimdall.infrastructure.store import InMemoryVectorStore

QUESTION = "что с alpha?"  # noqa: RUF001
QUESTION_STATE = cast(GraphState, {"question": QUESTION})


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


class DownChat:
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        del messages, tools
        raise ChatUnavailable("down")


class ExplodingList(InMemoryVectorStore):
    def __init__(self, inner: RecordingStore) -> None:
        super().__init__()
        self._inner = inner

    async def list_chunks(self) -> list[Chunk]:
        raise RuntimeError("db down")

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]:
        return await self._inner.search(query, embedder, k=k)


class CancelList(InMemoryVectorStore):
    async def list_chunks(self) -> list[Chunk]:
        raise asyncio.CancelledError()

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = RETRIEVE_TOP_K,
    ) -> list[Chunk]:
        del query, embedder, k
        raise AssertionError("search must not run")


def corpus() -> list[Chunk]:
    chunks = [
        Chunk(text="inventory.md\noverview", source="inventory.md"),
        Chunk(
            text="inventory.md\n## Alpha (note)\ncontainer alpha",
            source="inventory.md",
        ),
        Chunk(text="inventory.md\nstill alpha section", source="inventory.md"),
        Chunk(
            text="inventory.md\n## beta / gamma\ncontainer beta",
            source="inventory.md",
        ),
        Chunk(
            text="runbooks/alpha.md\n# Alpha\n\nalpha-0",
            source="runbooks/alpha.md",
        ),
    ]
    chunks.extend(
        Chunk(text=f"runbooks/alpha.md\nalpha-{index}", source="runbooks/alpha.md")
        for index in range(1, 6)
    )
    chunks.append(
        Chunk(
            text="runbooks/gamma.md\n# Gamma\n\ngamma body",
            source="runbooks/gamma.md",
        )
    )
    chunks.append(
        Chunk(
            text="runbooks/delta.md\n# Delta\n\ndelta only",
            source="runbooks/delta.md",
        )
    )
    return chunks


def payload(chunks: list[Chunk]) -> list[dict[str, str]]:
    return [{"text": chunk.text, "source": chunk.source} for chunk in chunks]


def alpha_payload(chunks: list[Chunk]) -> list[dict[str, str]]:
    return payload([*chunks[4:10], *chunks[1:3]])


async def loaded() -> tuple[RecordingStore, list[Chunk]]:
    store = RecordingStore()
    chunks = corpus()
    await store.upsert(chunks, FakeEmbedder())
    return store, chunks


def answer(sources: list[str]) -> str:
    return json.dumps({"sources": sources}, ensure_ascii=False)


async def run(
    store: InMemoryVectorStore,
    content: str,
    embedder: Embedder | None = None,
) -> tuple[StateUpdate, FakeChatModel]:
    chat = FakeChatModel([ScriptedTurn(content=content)])
    update = await retrieve(
        store,
        embedder if embedder is not None else FakeEmbedder(),
        chat,
    )(QUESTION_STATE)
    return update, chat


@pytest.mark.asyncio
async def test_exact_source_loads_file_and_section_without_search() -> None:
    store, chunks = await loaded()
    update, chat = await run(store, answer(["runbooks/alpha.md"]))
    assert store.searches == 0
    assert update["retrieved_chunks"] == alpha_payload(chunks)
    assert chat.calls[0]["tools"] is None
    messages = chat.calls[0]["messages"]
    assert isinstance(messages, list)
    assert messages[0].content == ROUTER_SYSTEM
    user = messages[1].content
    assert "Вопрос: что с alpha?" in user  # noqa: RUF001
    assert "source: runbooks/alpha.md" in user
    assert "title: # Alpha" in user
    assert "container alpha" in user
    assert "still alpha section" in user
    assert "alpha-0" not in user
    assert "overview" not in user
    texts = [item["text"] for item in update["retrieved_chunks"]]
    assert all("overview" not in text for text in texts)


@pytest.mark.asyncio
async def test_heading_note_matches_stem_and_later_token_does_not() -> None:
    store, chunks = await loaded()
    gamma, _chat = await run(store, answer(["runbooks/gamma.md"]))
    assert store.searches == 0
    assert gamma["retrieved_chunks"] == payload([chunks[10]])
    assert "container beta" not in gamma["retrieved_chunks"][0]["text"]

    store, chunks = await loaded()
    delta, _chat = await run(store, answer(["runbooks/delta.md"]))
    assert delta["retrieved_chunks"] == payload([chunks[11]])
    assert store.searches == 0


@pytest.mark.asyncio
async def test_unknown_second_name_keeps_the_first_file() -> None:
    store, chunks = await loaded()
    update, _chat = await run(
        store,
        answer(["runbooks/alpha.md", "runbooks/missing.md", "runbooks/alpha.md"]),
    )
    assert store.searches == 0
    assert update["retrieved_chunks"] == alpha_payload(chunks)


@pytest.mark.asyncio
async def test_sources_keep_model_order_then_each_section() -> None:
    store, chunks = await loaded()
    update, _chat = await run(
        store,
        answer(["runbooks/delta.md", "runbooks/alpha.md"]),
    )
    assert update["retrieved_chunks"] == payload(
        [chunks[11], *chunks[4:10], *chunks[1:3]]
    )


@pytest.mark.asyncio
async def test_non_string_source_is_ignored() -> None:
    store, chunks = await loaded()
    update, _chat = await run(
        store,
        '{"sources": [1, "runbooks/alpha.md"]}',
    )
    assert store.searches == 0
    assert update["retrieved_chunks"] == alpha_payload(chunks)


@pytest.mark.asyncio
async def test_duplicate_section_key_keeps_the_first_section() -> None:
    store = RecordingStore()
    chunks = [
        Chunk(text="inventory.md\n## Alpha\nfirst section", source="inventory.md"),
        Chunk(
            text="inventory.md\n## alpha extra\nsecond section",
            source="inventory.md",
        ),
        Chunk(text="runbooks/alpha.md\n# Alpha\n\nalpha-0", source="runbooks/alpha.md"),
    ]
    await store.upsert(chunks, FakeEmbedder())
    update, _chat = await run(store, answer(["runbooks/alpha.md"]))
    assert isinstance(update["retrieved_chunks"], list)
    texts = [item["text"] for item in update["retrieved_chunks"]]
    assert any("first section" in text for text in texts)
    assert all("second section" not in text for text in texts)


@pytest.mark.asyncio
async def test_shared_section_is_attached_once() -> None:
    store = RecordingStore()
    chunks = [
        Chunk(
            text="inventory.md\n## Alpha\ncontainer alpha",
            source="inventory.md",
        ),
        Chunk(
            text="runbooks/alpha.md\n# Alpha\n\nfrom runbooks",
            source="runbooks/alpha.md",
        ),
        Chunk(
            text="notes/alpha.md\n# Alpha\n\nfrom notes",
            source="notes/alpha.md",
        ),
    ]
    await store.upsert(chunks, FakeEmbedder())
    update, _chat = await run(
        store,
        answer(["runbooks/alpha.md", "notes/alpha.md"]),
    )
    assert isinstance(update["retrieved_chunks"], list)
    texts = [item["text"] for item in update["retrieved_chunks"]]
    assert texts == [
        "runbooks/alpha.md\n# Alpha\n\nfrom runbooks",
        "inventory.md\n## Alpha\ncontainer alpha",
        "notes/alpha.md\n# Alpha\n\nfrom notes",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"sources": []}',
        "not-json",
        '["runbooks/alpha.md"]',
        '{"sources": [" runbooks/alpha.md "]}',
        '{"sources": ["nope.md"]}',
        "{}",
    ],
)
async def test_unusable_router_answer_searches_and_drops_the_tail(
    content: str,
) -> None:
    store, _chunks = await loaded()
    update, chat = await run(store, content)
    assert store.searches == 1
    assert len(chat.calls) == 1
    assert isinstance(update["retrieved_chunks"], list)
    assert len(update["retrieved_chunks"]) == RETRIEVE_TOP_K


@pytest.mark.asyncio
async def test_empty_catalog_skips_the_model_and_searches() -> None:
    store = RecordingStore()
    chat = FakeChatModel([ScriptedTurn(content=answer(["runbooks/alpha.md"]))])
    update = await retrieve(store, FakeEmbedder(), chat)(QUESTION_STATE)
    assert chat.calls == []
    assert store.searches == 1
    assert update["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_inventory_only_catalog_skips_the_model() -> None:
    store = RecordingStore()
    await store.upsert(
        [Chunk(text="inventory.md\noverview", source="inventory.md")],
        FakeEmbedder(),
    )
    chat = FakeChatModel([ScriptedTurn(content=answer(["inventory.md"]))])
    update = await retrieve(store, FakeEmbedder(), chat)(QUESTION_STATE)
    assert chat.calls == []
    assert store.searches == 1
    assert update["retrieved_chunks"] == [
        {"text": "inventory.md\noverview", "source": "inventory.md"}
    ]


@pytest.mark.asyncio
async def test_chat_exception_falls_back_to_search() -> None:
    store, _chunks = await loaded()
    update = await retrieve(store, FakeEmbedder(), DownChat())(QUESTION_STATE)
    assert store.searches == 1
    assert isinstance(update["retrieved_chunks"], list)
    assert len(update["retrieved_chunks"]) == RETRIEVE_TOP_K


@pytest.mark.asyncio
async def test_list_chunks_exception_falls_back_to_search() -> None:
    store, _chunks = await loaded()
    update = await retrieve(ExplodingList(store), FakeEmbedder(), DownChat())(
        QUESTION_STATE
    )
    assert store.searches == 1
    assert isinstance(update["retrieved_chunks"], list)
    assert len(update["retrieved_chunks"]) == RETRIEVE_TOP_K


@pytest.mark.asyncio
async def test_cancelled_list_chunks_propagates() -> None:
    with pytest.raises(asyncio.CancelledError):
        await retrieve(CancelList(), FakeEmbedder(), DownChat())(QUESTION_STATE)


@pytest.mark.asyncio
async def test_embeddings_down_on_empty_choice_returns_empty() -> None:
    store, _chunks = await loaded()
    update, _chat = await run(store, answer([]), DownEmbedder())
    assert update["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_embeddings_down_on_named_file_still_loads_it() -> None:
    store, chunks = await loaded()
    update, _chat = await run(
        store,
        answer(["runbooks/alpha.md"]),
        DownEmbedder(),
    )
    assert store.searches == 0
    assert update["retrieved_chunks"] == alpha_payload(chunks)


@pytest.mark.asyncio
async def test_search_runtime_error_propagates() -> None:
    store, _chunks = await loaded()
    with pytest.raises(RuntimeError, match="boom"):
        await run(store, answer([]), BoomEmbedder())
