from fastapi import FastAPI

from heimdall.infrastructure.graph import AskRunner

from .routes import router


def create_app(runner: AskRunner) -> FastAPI:
    app = FastAPI()
    app.state.runner = runner
    app.include_router(router)
    return app
