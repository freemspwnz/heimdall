from heimdall.application.models import ChatMessage

from ...deps import GraphDeps
from ..prompts import VERIFY_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import (
    _context,
    _facts_block,
    _final_report,
    _observation_dict,
    _system_prompt,
    _text,
)


def _verify_context(state: GraphState, observations: list[dict[str, object]]) -> str:
    context = _context(state, observations)
    execution = state.get("execution_result")
    if execution is None:
        return context
    result = _facts_block([execution])
    return f"{context}\n\nРезультат команды:\n{result}"  # noqa: RUF001


async def verify(state: GraphState, deps: GraphDeps) -> StateUpdate:
    action = state.get("proposed_action") or {}
    target = _text(action.get("target"))
    observations = list(state.get("observations") or [])
    if target:
        observations.append(_observation_dict(await deps.docker.inspect(target)))
        observations.append(_observation_dict(await deps.docker.logs(target)))
    result = await deps.chat.complete(
        [
            ChatMessage(role="system", content=_system_prompt(VERIFY_SYSTEM, state)),
            ChatMessage(role="user", content=_verify_context(state, observations)),
        ]
    )
    report = _text(result.content) or _text(state.get("report"))
    return {
        "observations": observations,
        "report": _final_report(state, report, observations),
    }
