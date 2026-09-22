from typing import TypedDict

StateUpdate = dict[str, object]


class GraphState(TypedDict):
    question: str
    retrieved_chunks: list[dict[str, object]]
    observations: list[dict[str, object]]
    hypothesis: str | None
    confidence: float | None
    investigate_rounds: int
    proposed_action: dict[str, object] | None
    human_decision: str | None
    execution_result: dict[str, object] | None
    report: str | None
