import sys

import uvicorn

from .infrastructure.aiohttp import AgentClient, make_client_session
from .infrastructure.deps import Container
from .infrastructure.graph import LangGraphRunner, build_graph
from .infrastructure.settings import Settings
from .presentation.api import create_app
from .presentation.cli import run_repl

EMBEDDINGS_UNAVAILABLE = "эмбеддинги недоступны"
STARTUP_FAILED = "не удалось запустить агента, проверьте .env и доступность сервисов"
INGEST_FAILED = "не удалось проиндексировать базу знаний"


async def serve() -> int:
    settings = Settings()
    async with Container.open(settings) as c:
        graph = build_graph(deps=c.graph_deps, checkpointer=c.checkpointer)
        runner = LangGraphRunner(graph)
        app = create_app(
            graph=runner,
            store=c.store,
            embedder=c.embedder,
            knowledge_dir=c.knowledge_dir,
        )
        host, port = settings.parse_listen(settings.heimdall_listen)
        config = uvicorn.Config(app, host=host, port=port, log_config=None)
        server = uvicorn.Server(config)
        await server.serve()
    return 0


async def cli() -> int:
    try:
        async with make_client_session() as http:
            client = AgentClient(Settings.resolve_heimdall_url(), http)
            return await run_repl(client)
    except Exception as exc:
        print(f"{STARTUP_FAILED}: {exc}", file=sys.stderr)
        return 1
