from typing import Any

import pytest
from heimdall.providers import EmbeddingsUnavailable, LocalEmbedder


class _FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool = False,
    ) -> list[list[float]]:
        self.calls.append(
            {"texts": list(texts), "normalize_embeddings": normalize_embeddings}
        )
        return [[float(len(text)), 0.5] for text in texts]


@pytest.mark.asyncio
async def test_local_embedder_prefixes_passages_by_default() -> None:
    model = _FakeModel()
    embedder = LocalEmbedder(model=model)
    vectors = await embedder.embed(["postgres down", "traefik 502"])
    assert vectors == [
        [float(len("passage: postgres down")), 0.5],
        [float(len("passage: traefik 502")), 0.5],
    ]
    assert model.calls[0]["texts"] == [
        "passage: postgres down",
        "passage: traefik 502",
    ]
    assert model.calls[0]["normalize_embeddings"] is True


@pytest.mark.asyncio
async def test_local_embedder_prefixes_queries() -> None:
    model = _FakeModel()
    embedder = LocalEmbedder(model=model)
    question = "Chto s postgres?"
    vectors = await embedder.embed([question], query=True)
    assert model.calls[0]["texts"] == [f"query: {question}"]
    assert vectors == [[float(len(f"query: {question}")), 0.5]]


@pytest.mark.asyncio
async def test_local_embedder_empty_input_returns_empty() -> None:
    model = _FakeModel()
    embedder = LocalEmbedder(model=model)
    assert await embedder.embed([]) == []
    assert model.calls == []


def test_local_embedder_missing_package_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(model_name: str) -> object:
        raise EmbeddingsUnavailable("sentence-transformers is not installed")

    monkeypatch.setattr("heimdall.providers.local._load_sentence_transformer", boom)
    with pytest.raises(EmbeddingsUnavailable, match="sentence-transformers"):
        LocalEmbedder(model_name="intfloat/multilingual-e5-base")
