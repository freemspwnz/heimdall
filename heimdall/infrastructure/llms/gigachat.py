import json

from heimdall.application.exceptions import ChatUnavailable
from heimdall.application.models import ChatMessage, ChatResult, ToolSpec
from heimdall.application.protocols import Logger

from ..aiohttp import GigaChatClient
from ..settings import Settings


class GigaChatChatModel:
    def __init__(
        self,
        settings: Settings,
        http: GigaChatClient,
        logger: Logger,
    ) -> None:
        self._settings = settings
        self._http = http
        self._logger = logger
        self._base_url = settings.gigachat_base_url.rstrip("/")

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        tool_names = ",".join(spec.name for spec in tools) if tools else ""
        roles = ",".join(message.role for message in messages)
        self._logger.info(
            "model request model={} messages={} roles={} tools={}",
            self._settings.gigachat_chat_model,
            len(messages),
            roles,
            tool_names,
        )
        body: dict[str, object] = {
            "model": self._settings.gigachat_chat_model,
            "messages": [self._message_payload(message) for message in messages],
        }
        if tools is not None:
            body["functions"] = self._gigachat_functions(tools)
            body["function_call"] = "auto"
        url = f"{self._base_url}/chat/completions"
        try:
            parsed = await self._http.post_json(url, body, ChatUnavailable)
        except Exception:
            self._logger.exception(
                "model call failed model={}",
                self._settings.gigachat_chat_model,
            )
            raise
        result = self._parse_chat_result(parsed)
        content = (result.content or "").replace("\n", " ")[:160]
        calls = ",".join(
            f"{call.name}({json.dumps(call.arguments, ensure_ascii=False)})"
            for call in result.tool_calls
        )
        self._logger.info(
            "model response tool_calls={} content={}",
            calls,
            content,
        )
        return result

    @staticmethod
    def _gigachat_functions(tools: list[ToolSpec]) -> list[dict[str, object]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in tools
        ]

    @staticmethod
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

    def _parse_chat_result(self, payload: object) -> ChatResult:
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
            tool_calls=self._http.parse_function_call(message.get("function_call")),
        )
