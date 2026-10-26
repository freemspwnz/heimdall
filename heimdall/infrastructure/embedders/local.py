import asyncio

from sentence_transformers import SentenceTransformer

from heimdall.application.exceptions import EmbeddingsUnavailable

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


def load_sentence_transformer(model_name: str) -> SentenceTransformer:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingsUnavailable(
            "sentence-transformers is not installed; run: uv sync --group embeddings"
        ) from exc
    return SentenceTransformer(model_name)


class LocalEmbedder:
    """Local E5-style embedder via sentence-transformers.

    Applies ``query:`` / ``passage:`` prefixes required by multilingual-e5-*.
    """

    def __init__(
        self,
        *,
        model: SentenceTransformer,
    ) -> None:
        self._model = model

    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        if not texts:
            return []
        prefix = _QUERY_PREFIX if query else _PASSAGE_PREFIX
        prefixed = [prefix + text for text in texts]
        try:
            raw = await asyncio.to_thread(
                self._model.encode,
                prefixed,
                normalize_embeddings=True,
            )
        except Exception as exc:
            raise EmbeddingsUnavailable(str(exc)) from exc
        return [[float(value) for value in vector] for vector in raw]
