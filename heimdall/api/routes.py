from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from heimdall.runtime.events import RunEvent
from heimdall.runtime.runner import AskRunner

router = APIRouter()


class AskBody(BaseModel):
    question: str


class ResumeBody(BaseModel):
    decision: Literal["yes", "no"]


def _sse(event: RunEvent) -> bytes:
    payload: dict[str, object] = {"text": event.text}
    if event.run_id is not None:
        payload["run_id"] = event.run_id
    if event.action is not None:
        payload["action"] = {
            "tool": event.action.tool,
            "target": event.action.target,
            "reason": event.action.reason,
            "risk": event.action.risk,
        }
    return (
        f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    ).encode()


def _runner(request: Request) -> AskRunner:
    return cast(AskRunner, request.app.state.runner)

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/v1/ask")
async def ask(body: AskBody, request: Request) -> StreamingResponse:
    runner = _runner(request)

    async def event_stream() -> AsyncIterator[bytes]:
        run_id: str | None = None
        try:
            async for event in runner.ask(body.question):
                if event.run_id is not None:
                    run_id = event.run_id
                yield _sse(event)
        finally:
            if run_id is not None:
                await runner.cancel_hitl(run_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/runs/{run_id}/resume", status_code=204)
async def resume_run(run_id: str, body: ResumeBody, request: Request) -> Response:
    runner = _runner(request)
    result = await runner.resume(run_id, body.decision)
    if result == "unknown":
        raise HTTPException(status_code=404, detail="unknown run")
    if result == "not_waiting":
        raise HTTPException(status_code=409, detail="not waiting")
    return Response(status_code=204)
