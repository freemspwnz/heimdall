from heimdall.application.protocols import Docker

from ..state import GraphState, StateUpdate
from .utils import _observation_dict, _text


class execute:
    def __init__(self, docker: Docker) -> None:
        self._docker = docker

    async def __call__(self, state: GraphState) -> StateUpdate:
        action = state.get("proposed_action")
        if state.get("human_decision") != "yes" or action is None:
            return {}
        observation = await self._docker.restart(_text(action.get("target")))
        return {"execution_result": _observation_dict(observation)}
