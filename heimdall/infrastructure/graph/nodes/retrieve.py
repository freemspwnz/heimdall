from dataclasses import asdict

from heimdall.application.exceptions import EmbeddingsUnavailable
from heimdall.application.protocols import Embedder, VectorStore
from heimdall.domain.models import Chunk

from ...constants import RETRIEVE_TOP_K
from ..state import GraphState, StateUpdate


def _chunk_dict(chunk: Chunk) -> dict[str, object]:
    return asdict(chunk)


class retrieve:
    def __init__(self, retriever: VectorStore, embedder: Embedder) -> None:
        self._retriever = retriever
        self._embedder = embedder

    async def __call__(self, state: GraphState) -> StateUpdate:
        try:
            chunks = await self._retriever.search(
                state["question"],
                self._embedder,
                k=RETRIEVE_TOP_K,
            )
        except EmbeddingsUnavailable:
            chunks = []
        return {"retrieved_chunks": [_chunk_dict(chunk) for chunk in chunks]}
