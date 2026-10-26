from typing import Protocol


class HttpClient(Protocol):
    async def request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, str]: ...
