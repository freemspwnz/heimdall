from heimdall.application.models import ChatMessage
from heimdall.domain.models import Observation

from ...constants import MAX_TOOL_CALLS_PER_ROUND
from ...deps import GraphDeps
from ..prompts import INVESTIGATE_SYSTEM
from ..state import GraphState, StateUpdate
from ..tools import READ_TOOLS, run_tool
from .utils import _context, _observation_dict, _system_prompt


def _observation_text(observation: Observation) -> str:
    if observation.ok:
        return observation.payload
    return f"ошибка: {observation.error}"


async def investigate(state: GraphState, deps: GraphDeps) -> StateUpdate:
    observations = list(state.get("observations") or [])
    messages = [
        ChatMessage(role="system", content=_system_prompt(INVESTIGATE_SYSTEM, state)),
        ChatMessage(role="user", content=_context(state)),
    ]
    budget = MAX_TOOL_CALLS_PER_ROUND
    while budget > 0:
        result = await deps.chat.complete(messages, tools=READ_TOOLS)
        if not result.tool_calls:
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
            observation = await run_tool(deps, call)
            observations.append(_observation_dict(observation))
            messages.append(
                ChatMessage(
                    role="tool",
                    content=_observation_text(observation),
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
    rounds = state.get("investigate_rounds") or 0
    return {"investigate_rounds": rounds + 1, "observations": observations}
