from pathlib import Path

from heimdall.models import Chunk
from heimdall.providers.protocols import Embedder
from heimdall.rag.chunker import chunk_markdown
from heimdall.rag.store import VectorStore

_INVENTORY = "inventory.md"
_RUNBOOKS_GLOB = "*.md"


async def ingest_knowledge(
    knowledge_dir: Path,
    store: VectorStore,
    embedder: Embedder,
) -> int:
    chunks: list[Chunk] = []
    inventory = knowledge_dir / _INVENTORY
    if inventory.is_file():
        chunks.extend(_chunks_from(inventory, knowledge_dir))
    runbooks_dir = knowledge_dir / "runbooks"
    if runbooks_dir.is_dir():
        for path in sorted(runbooks_dir.glob(_RUNBOOKS_GLOB)):
            chunks.extend(_chunks_from(path, knowledge_dir))
    await store.upsert(chunks, embedder)
    return len(chunks)


def _chunks_from(path: Path, knowledge_dir: Path) -> list[Chunk]:
    source = path.relative_to(knowledge_dir).as_posix()
    return chunk_markdown(path.read_text(encoding="utf-8"), source)
