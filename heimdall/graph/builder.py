from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from heimdall.constants import (
    CONFIDENCE_RETRY_THRESHOLD,
    DEFAULT_CONFIDENCE,
    MAX_INVESTIGATE_ROUNDS,
)
from heimdall.graph import nodes
from heimdall.graph.nodes import Deps
from heimdall.graph.state import GraphState, StateUpdate
from heimdall.providers import ChatModel, Embedder
from heimdall.rag import VectorStore
from heimdall.tools import DockerClient, LokiClient, VictoriaMetricsClient

DepsNode = Callable[[GraphState, Deps], Awaitable[StateUpdate]]

CompiledGraph = CompiledStateGraph[GraphState, Any, GraphState, GraphState]


class Node(Protocol):
    def __call__(self, state: GraphState) -> Awaitable[StateUpdate]: ...


def build_graph(
    *,
    retriever: VectorStore,
    embedder: Embedder,
    chat: ChatModel,
    docker: DockerClient,
    loki: LokiClient,
    vm: VictoriaMetricsClient,
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledGraph:
    deps = Deps(
        retriever=retriever,
        embedder=embedder,
        chat=chat,
        docker=docker,
        loki=loki,
        vm=vm,
    )
    graph: StateGraph[GraphState, Any, GraphState, GraphState] = StateGraph(GraphState)
    graph.add_node("retrieve", _bind(nodes.retrieve, deps))
    graph.add_node("investigate", _bind(nodes.investigate, deps))
    graph.add_node("diagnose", _bind(nodes.diagnose, deps))
    graph.add_node("propose", _bind(nodes.propose, deps))
    graph.add_node("confirm", nodes.confirm)
    graph.add_node("execute", _bind(nodes.execute, deps))
    graph.add_node("verify", _bind(nodes.verify, deps))

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "investigate")
    graph.add_edge("investigate", "diagnose")
    graph.add_conditional_edges(
        "diagnose",
        _after_diagnose,
        {"investigate": "investigate", "propose": "propose"},
    )
    graph.add_conditional_edges(
        "propose",
        _after_propose,
        {"confirm": "confirm", "end": END},
    )
    graph.add_conditional_edges(
        "confirm",
        _after_confirm,
        {"execute": "execute", "end": END},
    )
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)


def _bind(node: DepsNode, deps: Deps) -> Node:
    async def run(state: GraphState) -> StateUpdate:
        return await node(state, deps)

    return run


def _after_diagnose(state: GraphState) -> str:
    confidence = state.get("confidence")
    value = DEFAULT_CONFIDENCE if confidence is None else confidence
    rounds = state.get("investigate_rounds") or 0
    if value < CONFIDENCE_RETRY_THRESHOLD and rounds < MAX_INVESTIGATE_ROUNDS:
        return "investigate"
    return "propose"


def _after_propose(state: GraphState) -> str:
    return "confirm" if state.get("proposed_action") else "end"


def _after_confirm(state: GraphState) -> str:
    return "execute" if state.get("human_decision") == "yes" else "end"
