from pathlib import Path

from fastapi import FastAPI

from heimdall.application.protocols import Embedder, Graph, VectorStore

from .routes import router


def create_app(
    *,
    graph: Graph,
    store: VectorStore,
    embedder: Embedder,
    knowledge_dir: Path,
) -> FastAPI:
    app = FastAPI()
    app.state.graph = graph
    app.state.store = store
    app.state.embedder = embedder
    app.state.knowledge_dir = knowledge_dir
    app.include_router(router)
    return app
