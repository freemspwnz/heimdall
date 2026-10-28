from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..deps import GraphDeps
from .edges import after_confirm, after_diagnose, after_propose
from .nodes import (
    confirm,
    diagnose,
    execute,
    investigate,
    propose,
    retrieve,
    verify,
)
from .state import GraphState
from .tools import Tools


def build_graph(
    *,
    deps: GraphDeps,
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[GraphState, Any, GraphState, GraphState]:
    tools = Tools(deps.docker, deps.loki, deps.vm, deps.logger)

    graph: StateGraph[GraphState, Any, GraphState, GraphState] = StateGraph(GraphState)
    graph.add_node(
        "retrieve",
        retrieve(deps.retriever, deps.embedder, deps.chat, deps.logger),
    )
    graph.add_node("investigate", investigate(deps.chat, tools))
    graph.add_node("diagnose", diagnose(deps.chat))
    graph.add_node("propose", propose(deps.chat))
    graph.add_node("confirm", confirm)
    graph.add_node("execute", execute(deps.docker))
    graph.add_node("verify", verify(deps.chat, deps.docker))

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "investigate")
    graph.add_edge("investigate", "diagnose")
    graph.add_conditional_edges(
        "diagnose",
        after_diagnose,
        {"investigate": "investigate", "propose": "propose"},
    )
    graph.add_conditional_edges(
        "propose",
        after_propose,
        {"confirm": "confirm", "end": END},
    )
    graph.add_conditional_edges(
        "confirm",
        after_confirm,
        {"execute": "execute", "end": END},
    )
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)
