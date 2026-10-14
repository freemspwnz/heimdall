from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from heimdall.application.protocols import ChatModel, Embedder, VectorStore

from ..aiohttp import DockerClient, LokiClient, VictoriaMetricsClient
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
from .state import GraphState, StateUpdate

DepsNode = Callable[[GraphState, GraphDeps], Awaitable[StateUpdate]]

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
    deps = GraphDeps(
        retriever=retriever,
        embedder=embedder,
        chat=chat,
        docker=docker,
        loki=loki,
        vm=vm,
    )
    graph: StateGraph[GraphState, Any, GraphState, GraphState] = StateGraph(GraphState)
    graph.add_node("retrieve", _bind(retrieve, deps))
    graph.add_node("investigate", _bind(investigate, deps))
    graph.add_node("diagnose", _bind(diagnose, deps))
    graph.add_node("propose", _bind(propose, deps))
    graph.add_node("confirm", confirm)
    graph.add_node("execute", _bind(execute, deps))
    graph.add_node("verify", _bind(verify, deps))

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


def _bind(node: DepsNode, deps: GraphDeps) -> Node:
    async def run(state: GraphState) -> StateUpdate:
        return await node(state, deps)

    return run

