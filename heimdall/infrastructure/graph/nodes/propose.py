import json
import re
from dataclasses import asdict

from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel
from heimdall.domain.models import Action

from ...constants import NEVER_RESTART
from ..prompts import PROPOSE_SYSTEM
from ..state import GraphState, StateUpdate
from ..tools.registry import DOCKER_INSPECT
from .utils import _context, _final_report, _parse_json_object, _system_prompt, _text


class propose:
    _DOWN_STATUSES = frozenset({"exited", "dead", "restarting"})
    _STATUS_RE = re.compile(
        r'"Status"\s*:\s*"(running|created|restarting|removing|paused|exited|dead)"'
    )
    _HEALTH_RE = re.compile(r'"Health"\s*:\s*\{[^{}]*"Status"\s*:\s*"([^"]+)"')

    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def __call__(self, state: GraphState) -> StateUpdate:
        result = await self._chat.complete(
            [
                ChatMessage(
                    role="system", content=_system_prompt(PROPOSE_SYSTEM, state)
                ),
                ChatMessage(role="user", content=_context(state)),
            ]
        )
        data = _parse_json_object(result.content)
        report = _text(data.get("report")) or _text(state.get("report"))
        action = self._parse_action(data.get("action"))
        observations = state.get("observations") or []
        if action is None or not self._container_is_down(observations, action.target):
            return {"proposed_action": None, "report": _final_report(state, report)}
        return {"proposed_action": asdict(action), "report": report or None}

    @staticmethod
    def _parse_action(value: object) -> Action | None:
        if not isinstance(value, dict):
            return None
        tool = _text(value.get("tool")) or "restart"
        if tool != "restart":
            return None
        target = _text(value.get("target"))
        if not target or target in NEVER_RESTART:
            return None
        return Action(
            tool=tool,
            target=target,
            reason=_text(value.get("reason")),
            risk=_text(value.get("risk")),
        )

    @classmethod
    def _container_is_down(
        cls,
        observations: list[dict[str, object]],
        target: str,
    ) -> bool:
        payload = cls._last_inspect_payload(observations, target)
        if payload is None:
            return False
        state = cls._read_state(payload)
        if state is None:
            return False
        status, health = state
        if status in cls._DOWN_STATUSES:
            return True
        return health == "unhealthy"

    @staticmethod
    def _last_inspect_payload(
        observations: list[dict[str, object]],
        target: str,
    ) -> str | None:
        payload: str | None = None
        for item in observations:
            if item.get("tool") != DOCKER_INSPECT or item.get("target") != target:
                continue
            if item.get("ok") is not True:
                continue
            raw = item.get("payload")
            if isinstance(raw, str):
                payload = raw
        return payload

    @classmethod
    def _read_state(cls, payload: str) -> tuple[str, str] | None:
        parsed = cls._parse_object(payload)
        if parsed is not None:
            return cls._state_from_object(parsed)
        return cls._state_from_text(payload)

    @staticmethod
    def _parse_object(payload: str) -> dict[str, object] | None:
        try:
            parsed: object = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return {str(key): value for key, value in parsed.items()}
        return None

    @staticmethod
    def _state_from_object(parsed: dict[str, object]) -> tuple[str, str] | None:
        state = parsed.get("State")
        if not isinstance(state, dict):
            return None
        status = state.get("Status")
        health_block = state.get("Health")
        health = ""
        if isinstance(health_block, dict):
            raw = health_block.get("Status")
            if isinstance(raw, str):
                health = raw
        return (status if isinstance(status, str) else "", health)

    @classmethod
    def _state_from_text(cls, payload: str) -> tuple[str, str] | None:
        status_match = cls._STATUS_RE.search(payload)
        health_match = cls._HEALTH_RE.search(payload)
        if status_match is None and health_match is None:
            return None
        status = status_match.group(1) if status_match is not None else ""
        health = health_match.group(1) if health_match is not None else ""
        return status, health
