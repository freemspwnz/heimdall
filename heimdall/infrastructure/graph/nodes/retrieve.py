from dataclasses import asdict

from heimdall.application.exceptions import EmbeddingsUnavailable
from heimdall.domain.models import Chunk

from ...constants import RETRIEVE_TOP_K
from ...deps import GraphDeps
from ..state import GraphState, StateUpdate


def _chunk_dict(chunk: Chunk) -> dict[str, object]:
    return asdict(chunk)


async def retrieve(state: GraphState, deps: GraphDeps) -> StateUpdate:
    try:
        chunks = await deps.retriever.search(
            state["question"],
            deps.embedder,
            k=RETRIEVE_TOP_K,
        )
    except EmbeddingsUnavailable:
        chunks = []
    return {"retrieved_chunks": [_chunk_dict(chunk) for chunk in chunks]}
