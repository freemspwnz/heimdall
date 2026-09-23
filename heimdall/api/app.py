from __future__ import annotations

from fastapi import FastAPI

from heimdall.api.routes import router
from heimdall.runtime.runner import AskRunner


def create_app(runner: AskRunner) -> FastAPI:
    app = FastAPI()
    app.state.runner = runner
    app.include_router(router)
    return app
