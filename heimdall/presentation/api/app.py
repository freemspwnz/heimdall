from pathlib import Path

from fastapi import FastAPI

from heimdall.application.protocols import Chunker, Embedder, Graph, Loader, VectorStore

from .routes import router


def create_app(
    *,
    graph: Graph,
    store: VectorStore,
    embedder: Embedder,
    chunker: Chunker,
    loader: Loader,
    knowledge_dir: Path,
) -> FastAPI:
    app = FastAPI()
    app.state.graph = graph
    app.state.store = store
    app.state.embedder = embedder
    app.state.chunker = chunker
    app.state.loader = loader
    app.state.knowledge_dir = knowledge_dir
    app.include_router(router)
    return app
