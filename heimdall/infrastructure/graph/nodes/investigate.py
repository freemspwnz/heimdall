from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel
from heimdall.domain.models import Observation

from ...constants import MAX_TOOL_CALLS_PER_ROUND
from ..prompts import INVESTIGATE_SYSTEM
from ..state import GraphState, StateUpdate
from ..tools import READ_TOOLS, Tools
from .utils import _context, _observation_dict


def _observation_text(observation: Observation) -> str:
    if observation.ok:
        return observation.payload
    return f"ошибка: {observation.error}"


class investigate:
    def __init__(self, chat: ChatModel, tools: Tools) -> None:
        self._chat = chat
        self._tools = tools

    async def __call__(self, state: GraphState) -> StateUpdate:
        observations = list(state.get("observations") or [])
        before = len(observations)
        messages = [
            ChatMessage(role="system", content=INVESTIGATE_SYSTEM),
            ChatMessage(role="user", content=_context(state)),
        ]
        budget = MAX_TOOL_CALLS_PER_ROUND
        notes_delta = ""
        while budget > 0:
            result = await self._chat.complete(
                messages, tools=READ_TOOLS, node="investigate"
            )
            if not result.tool_calls:
                notes_delta = (result.content or "").strip()
                break
            calls = result.tool_calls[:budget]
            budget -= len(calls)
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=result.content or "",
                    tool_calls=calls,
                )
            )
            for call in calls:
                observation = await self._tools(call)
                observations.append(_observation_dict(observation))
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=_observation_text(observation),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
        previous = (state.get("investigation_notes") or "").strip()
        notes: str | None = state.get("investigation_notes")
        if notes_delta:
            notes = f"{previous}\n\n{notes_delta}" if previous else notes_delta

        rounds = state.get("investigate_rounds") or 0
        return {
            "investigate_rounds": rounds + 1,
            "observations": observations,
            "investigation_notes": notes,
            "investigate_gained_observations": len(observations) > before,
        }
