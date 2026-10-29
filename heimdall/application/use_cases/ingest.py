from pathlib import Path

from heimdall.domain.chunker import chunk_markdown
from heimdall.domain.models import Chunk

from ..exceptions import KnowledgeUnavailable
from ..protocols import Embedder, VectorStore

_INVENTORY = "inventory.md"
_RUNBOOKS_GLOB = "*.md"


async def ingest(
    knowledge_dir: Path,
    store: VectorStore,
    embedder: Embedder,
) -> int:
    chunks = _load_chunks(knowledge_dir)
    await store.upsert(chunks, embedder)
    return len(chunks)


def _load_chunks(knowledge_dir: Path) -> list[Chunk]:
    if not knowledge_dir.is_dir():
        raise KnowledgeUnavailable(f"knowledge directory not found: {knowledge_dir}")
    chunks: list[Chunk] = []
    inventory = knowledge_dir / _INVENTORY
    if inventory.is_file():
        chunks.extend(_chunks_from(inventory, knowledge_dir))
    runbooks_dir = knowledge_dir / "runbooks"
    if runbooks_dir.is_dir():
        for path in sorted(runbooks_dir.glob(_RUNBOOKS_GLOB)):
            chunks.extend(_chunks_from(path, knowledge_dir))
    if not chunks:
        raise KnowledgeUnavailable(f"knowledge directory is empty: {knowledge_dir}")
    return chunks


def _chunks_from(path: Path, knowledge_dir: Path) -> list[Chunk]:
    source = path.relative_to(knowledge_dir).as_posix()
    return chunk_markdown(path.read_text(encoding="utf-8"), source)
