from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import uuid4

from langgraph.types import Command

from heimdall.graph import CompiledGraph, GraphState
from heimdall.runtime.events import RunEvent
from heimdall.runtime.state import is_interrupted, pending_action, report

BUSY_TEXT = "agent is busy"
BROKEN_PROPOSAL = "агент предложил действие, которое не удалось разобрать"


class AskRunner:
    def __init__(self, graph: CompiledGraph) -> None:
        self._graph = graph
        self._lock = asyncio.Lock()
        self._waiting: dict[str, asyncio.Future[Literal["yes", "no"]]] = {}

    async def ask(self, question: str) -> AsyncIterator[RunEvent]:
        if self._lock.locked():
            yield RunEvent(type="busy", text=BUSY_TEXT)
            return

        await self._lock.acquire()
        run_id = str(uuid4())
        config: dict[str, Any] = {"configurable": {"thread_id": run_id}}
        try:
            try:
                payload: object = _initial_state(question)
                while True:
                    async for update in self._graph.astream(
                        payload,
                        config,
                        stream_mode="updates",
                    ):
                        if not isinstance(update, dict):
                            continue
                        for node_name in update:
                            if node_name == "__interrupt__":
                                continue
                            yield RunEvent(
                                type="status",
                                text=str(node_name),
                                run_id=run_id,
                            )

                    state = await self._read_state(config)
                    if is_interrupted(state):
                        action = pending_action(state)
                        if action is None:
                            yield RunEvent(
                                type="error",
                                text=BROKEN_PROPOSAL,
                                run_id=run_id,
                            )
                            return
                        decision_future = self._register_wait(run_id)
                        yield RunEvent(
                            type="hitl",
                            run_id=run_id,
                            action=action,
                        )
                        decision = await self._await_decision(run_id, decision_future)
                        payload = Command(resume=decision)
                        continue

                    yield RunEvent(
                        type="report",
                        text=report(state),
                        run_id=run_id,
                    )
                    return
            except Exception as exc:
                yield RunEvent(type="error", text=str(exc), run_id=run_id)
        finally:
            self._lock.release()

    async def resume(self, run_id: str, decision: Literal["yes", "no"]) -> None:
        future = self._waiting.get(run_id)
        if future is not None and not future.done():
            future.set_result(decision)

    async def cancel_hitl(self, run_id: str) -> None:
        await self.resume(run_id, "no")

    def _register_wait(self, run_id: str) -> asyncio.Future[Literal["yes", "no"]]:
        future: asyncio.Future[Literal["yes", "no"]] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiting[run_id] = future
        return future

    async def _await_decision(
        self,
        run_id: str,
        future: asyncio.Future[Literal["yes", "no"]],
    ) -> Literal["yes", "no"]:
        try:
            return await future
        except asyncio.CancelledError:
            if not future.done():
                future.set_result("no")
            return "no"
        finally:
            self._waiting.pop(run_id, None)

    async def _read_state(self, config: dict[str, Any]) -> dict[str, Any]:
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values
        state = dict(values) if isinstance(values, dict) else {}
        interrupts = getattr(snapshot, "interrupts", None) or ()
        if interrupts:
            state["__interrupt__"] = list(interrupts)
        return state


def _initial_state(question: str) -> GraphState:
    return GraphState(
        question=question,
        retrieved_chunks=[],
        observations=[],
        hypothesis=None,
        confidence=None,
        investigate_rounds=0,
        proposed_action=None,
        human_decision=None,
        execution_result=None,
        report=None,
    )
