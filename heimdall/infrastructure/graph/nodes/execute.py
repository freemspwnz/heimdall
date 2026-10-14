from ...deps import GraphDeps
from ..state import GraphState, StateUpdate
from .utils import _observation_dict, _text


async def execute(state: GraphState, deps: GraphDeps) -> StateUpdate:
    action = state.get("proposed_action")
    if state.get("human_decision") != "yes" or action is None:
        return {}
    observation = await deps.docker.restart(_text(action.get("target")))
    return {"execution_result": _observation_dict(observation)}
