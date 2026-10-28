import re
from dataclasses import asdict
from pathlib import PurePosixPath

from heimdall.application.exceptions import EmbeddingsUnavailable
from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel, Embedder, VectorStore
from heimdall.domain.models import Chunk

from ...constants import RETRIEVE_TOP_K
from ..prompts import ROUTER_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import _parse_json_object

_INVENTORY = "inventory.md"
_TITLE = re.compile(r"^#{1,6}\s+\S")
_SECTION = re.compile(r"^#{2,}\s+(\S+)")


def _chunk_dict(chunk: Chunk) -> dict[str, object]:
    return asdict(chunk)


class retrieve:
    def __init__(
        self,
        retriever: VectorStore,
        embedder: Embedder,
        chat: ChatModel,
    ) -> None:
        self._retriever = retriever
        self._embedder = embedder
        self._chat = chat

    async def __call__(self, state: GraphState) -> StateUpdate:
        try:
            chunks = await self._retriever.list_chunks()
        except Exception:
            return await self._search(state)
        chosen = await self._choose(state["question"], chunks)
        if not chosen:
            return await self._search(state)
        return {"retrieved_chunks": [_chunk_dict(chunk) for chunk in chosen]}

    async def _choose(self, question: str, chunks: list[Chunk]) -> list[Chunk]:
        grouped = _group(chunks)
        routable = [source for source in grouped if source != _INVENTORY]
        if not routable:
            return []
        try:
            result = await self._chat.complete(
                [
                    ChatMessage(role="system", content=ROUTER_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=_router_user(question, grouped, routable),
                    ),
                ]
            )
        except Exception:
            return []
        selected = _selected_sources(result.content, set(routable))
        if not selected:
            return []
        sections = _inventory_sections(grouped.get(_INVENTORY, []))
        attached: set[str] = set()
        chosen: list[Chunk] = []
        for source in selected:
            chosen.extend(grouped[source])
            key = PurePosixPath(source).stem.casefold()
            if key in attached:
                continue
            section = sections.get(key)
            if section is None:
                continue
            chosen.extend(section)
            attached.add(key)
        return chosen

    async def _search(self, state: GraphState) -> StateUpdate:
        try:
            chunks = await self._retriever.search(
                state["question"],
                self._embedder,
                k=RETRIEVE_TOP_K,
            )
        except EmbeddingsUnavailable:
            chunks = []
        return {"retrieved_chunks": [_chunk_dict(chunk) for chunk in chunks]}


def _group(chunks: list[Chunk]) -> dict[str, list[Chunk]]:
    grouped: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.source, []).append(chunk)
    return grouped


def _router_user(
    question: str,
    grouped: dict[str, list[Chunk]],
    routable: list[str],
) -> str:
    sections = _inventory_sections(grouped.get(_INVENTORY, []))
    blocks = [
        _catalog_block(source, grouped[source], sections) for source in routable
    ]
    return f"Вопрос: {question}\n\nКаталог:\n\n" + "\n\n".join(blocks)  # noqa: RUF001


def _catalog_block(
    source: str,
    chunks: list[Chunk],
    sections: dict[str, list[Chunk]],
) -> str:
    lines = [f"source: {source}"]
    title = _title(chunks)
    if title is not None:
        lines.append(f"title: {title}")
    section = sections.get(PurePosixPath(source).stem.casefold())
    if section is not None:
        lines.append(_section_body(section))
    return "\n".join(lines)


def _title(chunks: list[Chunk]) -> str | None:
    for chunk in chunks:
        for line in chunk.text.splitlines():
            if _TITLE.match(line):
                return line
    return None


def _section_body(chunks: list[Chunk]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        lines = chunk.text.splitlines()
        if lines and lines[0] == chunk.source:
            lines = lines[1:]
        parts.append("\n".join(lines))
    return "\n".join(parts)


def _inventory_sections(chunks: list[Chunk]) -> dict[str, list[Chunk]]:
    sections: dict[str, list[Chunk]] = {}
    current_key: str | None = None
    for chunk in chunks:
        opened = _section_key(chunk)
        if opened is not None:
            if opened in sections:
                current_key = None
            else:
                current_key = opened
                sections[opened] = [chunk]
            continue
        if current_key is not None:
            sections[current_key].append(chunk)
    return sections


def _section_key(chunk: Chunk) -> str | None:
    for line in chunk.text.splitlines():
        match = _SECTION.match(line)
        if match is not None:
            return match.group(1).casefold()
    return None


def _selected_sources(content: str | None, catalog: set[str]) -> list[str]:
    raw = _parse_json_object(content).get("sources")
    if not isinstance(raw, list):
        return []
    chosen: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or item not in catalog or item in seen:
            continue
        seen.add(item)
        chosen.append(item)
    return chosen
