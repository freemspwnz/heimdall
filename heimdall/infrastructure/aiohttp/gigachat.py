import json
import time
import uuid
from typing import ClassVar

import aiohttp

from heimdall.application.models import ToolCall

from ..settings import Settings
from .utils import timeout


class GigaChatClient:
    HTTP_TIMEOUT_SECONDS: ClassVar[int] = 60
    TOKEN_REMAINING_SECONDS: ClassVar[int] = 300  # 5 minutes

    def __init__(self, settings: Settings, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._session = session
        self._verify_ssl = settings.gigachat_verify_ssl
        self._token: str | None = None
        self._expires_at: float | None = None

    async def _request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, str]:
        _timeout = timeout(self.HTTP_TIMEOUT_SECONDS)
        if json_body is not None:
            cm = self._session.post(
                url,
                headers=headers,
                json=json_body,
                timeout=_timeout,
                ssl=self._verify_ssl,
            )
        else:
            cm = self._session.post(
                url,
                headers=headers,
                data=data,
                timeout=_timeout,
                ssl=self._verify_ssl,
            )
        async with cm as resp:
            text = await resp.text()
            return resp.status, text

    async def access_token(self, error: type[Exception]) -> str:
        if (
            self._token is not None
            and self._expires_at is not None
            and self._expires_at - time.time() > self.TOKEN_REMAINING_SECONDS
        ):
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
        token = self._parse_access_token(parsed)
        expires_at = self._parse_expires_at(parsed)
        if token is None:
            raise error("missing access_token")
        if expires_at is None:
            raise error("missing expires_at")
        self._token = token
        self._expires_at = expires_at
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
        if status == 401:
            self._token = None
            self._expires_at = None
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

    def parse_function_call(self, raw: object) -> list[ToolCall]:
        if not isinstance(raw, dict):
            return []
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return []
        return [
            ToolCall(
                id=f"fc-{uuid.uuid4()}",
                name=name,
                arguments=self._parse_arguments(raw.get("arguments")),
            )
        ]

    @staticmethod
    def _parse_access_token(payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        token = payload.get("access_token")
        return token if isinstance(token, str) and token else None

    @staticmethod
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

    @staticmethod
    def _parse_expires_at(payload: object) -> float | None:
        if not isinstance(payload, dict):
            return None
        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, int):
            return None
        return float(expires_at / 1000)
