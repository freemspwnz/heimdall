from heimdall.application.exceptions import EmbeddingsUnavailable
from heimdall.application.protocols import Embedder, Logger, VectorStore

from ...constants import RETRIEVE_TOP_K
from ..state import GraphState, StateUpdate


class retrieve:
    def __init__(
        self,
        retriever: VectorStore,
        embedder: Embedder,
        logger: Logger,
    ) -> None:
        self._retriever = retriever
        self._embedder = embedder
        self._logger = logger

    async def __call__(self, state: GraphState) -> StateUpdate:
        question = state["question"]
        self._logger.info("question {}", question.replace("\n", " "))
        loaded = self._read_runbooks(state.get("runbooks"))
        if loaded:
            return self._log_sources(self._logger, {"retrieved_chunks": loaded})
        return await self._search(state)

    async def _search(self, state: GraphState) -> StateUpdate:
        try:
            chunks = await self._retriever.search(
                state["question"],
                self._embedder,
                k=RETRIEVE_TOP_K,
            )
        except EmbeddingsUnavailable:
            chunks = []
        return self._log_sources(
            self._logger,
            {
                "retrieved_chunks": [
                    {"text": chunk.text, "source": chunk.source} for chunk in chunks
                ]
            },
        )

    @staticmethod
    def _read_runbooks(raw: object) -> list[dict[str, str]]:
        from ..paths import RUNBOOKS_DIR

        if not isinstance(raw, list):
            return []
        loaded: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or not _bare_name(item) or item in seen:
                continue
            seen.add(item)
            try:
                text = (RUNBOOKS_DIR / item).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            loaded.append({"text": text, "source": f"runbooks/{item}"})
        return loaded


    @staticmethod
    def _log_sources(logger: Logger, update: StateUpdate) -> StateUpdate:
        chunks = update.get("retrieved_chunks") or []
        names: list[str] = []
        seen: set[str] = set()
        if isinstance(chunks, list):
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                source = chunk.get("source")
                if isinstance(source, str) and source and source not in seen:
                    seen.add(source)
                    names.append(source)
        logger.info("sources={}", ",".join(names))
        return update


def _bare_name(name: str) -> bool:
    return (
        bool(name) and name not in {".", ".."} and "/" not in name and "\\" not in name
    )
