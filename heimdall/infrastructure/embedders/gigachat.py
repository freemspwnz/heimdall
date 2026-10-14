from heimdall.application.exceptions import EmbeddingsUnavailable

from ..aiohttp import GigaChatClient
from ..settings import Settings

GIGACHAT_EMBEDDINGS_MODEL = "Embeddings"


class GigaChatEmbedder:
    def __init__(self, settings: Settings, http: GigaChatClient) -> None:
        self._http = http
        self._base_url = settings.gigachat_base_url.rstrip("/")

    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del query
        url = f"{self._base_url}/embeddings"
        parsed = await self._http.post_json(
            url,
            {"model": GIGACHAT_EMBEDDINGS_MODEL, "input": texts},
            EmbeddingsUnavailable,
        )
        return self._parse_embeddings(parsed)

    @staticmethod
    def _parse_embeddings(payload: object) -> list[list[float]]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        vectors: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            embedding = item.get("embedding")
            if isinstance(embedding, list) and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in embedding
            ):
                vectors.append([float(value) for value in embedding])
        return vectors
