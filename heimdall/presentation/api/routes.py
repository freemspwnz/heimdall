import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from heimdall.application.exceptions import KnowledgeUnavailable
from heimdall.application.models import RunEvent
from heimdall.application.protocols import Graph
from heimdall.application.use_cases import decide, ingest_knowledge, investigate

router = APIRouter()


class AskBody(BaseModel):
    question: str


class ResumeBody(BaseModel):
    decision: bool


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


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/v1/ingest")
async def ingest(request: Request) -> dict[str, int]:
    try:
        count = await ingest_knowledge(
            request.app.state.knowledge_dir,
            request.app.state.store,
            request.app.state.embedder,
        )
    except KnowledgeUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": count}


@router.post("/v1/ask")
async def ask(body: AskBody, request: Request) -> StreamingResponse:

    async def event_stream() -> AsyncIterator[bytes]:
        run_id: str | None = None
        graph: Graph = request.app.state.graph
        try:
            async for event in investigate(body.question, graph):
                if event.run_id is not None:
                    run_id = event.run_id
                yield _sse(event)
        except asyncio.CancelledError:
            # Client disconnected mid-stream (often while waiting on HITL).
            if run_id is not None:
                await graph.decide(run_id, False)
            raise

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/runs/{run_id}/resume", status_code=204)
async def resume_run(run_id: str, body: ResumeBody, request: Request) -> Response:
    result = await decide(run_id, body.decision, request.app.state.graph)
    if result == "unknown":
        raise HTTPException(status_code=404, detail="unknown run")
    if result == "not_waiting":
        raise HTTPException(status_code=409, detail="not waiting")
    return Response(status_code=204)
