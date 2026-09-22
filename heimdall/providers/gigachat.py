import json
import uuid

import aiohttp

from heimdall.constants import HTTP_TIMEOUT_SECONDS
from heimdall.models import ChatMessage, ChatResult, ToolCall, ToolSpec
from heimdall.providers.protocols import ChatUnavailable, EmbeddingsUnavailable
from heimdall.settings import Settings

GIGACHAT_EMBEDDINGS_MODEL = "Embeddings"


def _timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)


def _parse_access_token(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    token = payload.get("access_token")
    return token if isinstance(token, str) and token else None


def _gigachat_functions(tools: list[ToolSpec]) -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in tools
    ]


def _message_payload(message: ChatMessage) -> dict[str, object]:
    if message.role == "tool":
        payload: dict[str, object] = {
            "role": "function",
            "content": json.dumps({"result": message.content}, ensure_ascii=False),
        }
        if message.name is not None:
            payload["name"] = message.name
        return payload

    payload = {"role": message.role, "content": message.content}
    if message.tool_calls:
        call = message.tool_calls[0]  # GigaChat: one call per assistant turn
        payload["function_call"] = {
            "name": call.name,
            "arguments": call.arguments,
        }
    return payload


def _parse_arguments(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, str):
        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(key): value for key, value in parsed.items()}
    return {}


def _parse_function_call(raw: object) -> list[ToolCall]:
    if not isinstance(raw, dict):
        return []
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return []
    return [
        ToolCall(
            id=f"fc-{uuid.uuid4()}",
            name=name,
            arguments=_parse_arguments(raw.get("arguments")),
        )
    ]


def _parse_chat_result(payload: object) -> ChatResult:
    if not isinstance(payload, dict):
        return ChatResult()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ChatResult()
    first = choices[0]
    if not isinstance(first, dict):
        return ChatResult()
    message = first.get("message")
    if not isinstance(message, dict):
        return ChatResult()
    content_raw = message.get("content")
    content = content_raw if isinstance(content_raw, str) else None
    return ChatResult(
        content=content,
        tool_calls=_parse_function_call(message.get("function_call")),
    )


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


class _GigaChatHttp:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._session = session
        self._verify_ssl = settings.gigachat_verify_ssl
        self._token: str | None = None

    async def _request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, str]:
        timeout = _timeout()
        if json_body is not None:
            cm = self._session.post(
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
                ssl=self._verify_ssl,
            )
        else:
            cm = self._session.post(
                url,
                headers=headers,
                data=data,
                timeout=timeout,
                ssl=self._verify_ssl,
            )
        async with cm as resp:
            text = await resp.text()
            return resp.status, text

    async def access_token(self, error: type[Exception]) -> str:
        if self._token is not None:
            return self._token
        headers = {
            "Authorization": f"Basic {self._settings.gigachat_credentials}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            status, text = await self._request(
                self._settings.gigachat_oauth_url,
                headers=headers,
                data={"scope": self._settings.gigachat_scope},
            )
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise error(str(exc)) from exc
        if status != 200:
            raise error(f"{status} {text}")
        try:
            parsed: object = json.loads(text)
        except json.JSONDecodeError as exc:
            raise error(str(exc)) from exc
        token = _parse_access_token(parsed)
        if token is None:
            raise error("missing access_token")
        self._token = token
        return token

    async def post_json(
        self,
        url: str,
        body: dict[str, object],
        error: type[Exception],
    ) -> object:
        token = await self.access_token(error)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            status, text = await self._request(url, headers=headers, json_body=body)
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise error(str(exc)) from exc
        if status != 200:
            raise error(f"{status} {text}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise error(str(exc)) from exc


class GigaChatChatModel:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._http = _GigaChatHttp(settings, session)
        self._base_url = settings.gigachat_base_url.rstrip("/")

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        body: dict[str, object] = {
            "model": self._settings.gigachat_chat_model,
            "messages": [_message_payload(message) for message in messages],
        }
        if tools is not None:
            body["functions"] = _gigachat_functions(tools)
            body["function_call"] = "auto"
        url = f"{self._base_url}/chat/completions"
        parsed = await self._http.post_json(url, body, ChatUnavailable)
        return _parse_chat_result(parsed)


class GigaChatEmbedder:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession) -> None:
        self._http = _GigaChatHttp(settings, session)
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
        return _parse_embeddings(parsed)
