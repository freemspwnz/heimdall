from typing import Protocol


class Embedder(Protocol):
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]: ...
