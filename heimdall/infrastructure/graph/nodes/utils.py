import json
from dataclasses import asdict

from heimdall.domain.models import Observation

from ..prompts import (
    COVERAGE_NOTE,
    EMPTY_REPORT,
    TUNNEL_DISCLAIMER,
    TUNNEL_PROMPT_RULE,
)
from ..state import GraphState

EMPTY_PAYLOADS = frozenset({"no streams", "no data"})
TUNNEL_MARKERS = ("туннел", "tunnel", "vpn", "3x-ui")


def _observation_dict(observation: Observation) -> dict[str, object]:
    return asdict(observation)


def _context(
    state: GraphState,
    observations: list[dict[str, object]] | None = None,
) -> str:
    facts = state.get("observations") or [] if observations is None else observations
    return "\n\n".join(
        [
            f"Вопрос: {state['question']}",
            f"Знания из инвентаря и runbook:\n{_chunks_block(state)}",
            f"Наблюдения:\n{_facts_block(facts)}",
        ]
    )


def _chunks_block(state: GraphState) -> str:
    chunks = state.get("retrieved_chunks") or []
    if not chunks:
        return "Runbook-и недоступны, опирайся только на факты из инструментов."
    return "\n".join(
        f"[{_text(chunk.get('source'))}] {_text(chunk.get('text'))}" for chunk in chunks
    )


def _facts_block(observations: list[dict[str, object]]) -> str:
    if not observations:
        return "Фактов пока нет."
    blocks: list[str] = []
    for observation in observations:
        source = _text(observation.get("source"))
        if observation.get("ok"):
            status = "ок"
        else:
            status = f"ошибка: {_text(observation.get('error'))}"
        blocks.append(f"[{source}] {status}\n{_text(observation.get('payload'))}")
    return "\n\n".join(blocks)


def _system_prompt(base: str, state: GraphState) -> str:
    if _is_tunnel_question(state["question"]):
        return f"{base}\n{TUNNEL_PROMPT_RULE}"
    return base


def _is_tunnel_question(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in TUNNEL_MARKERS)


def _final_report(
    state: GraphState,
    report: str,
    observations: list[dict[str, object]] | None = None,
) -> str:
    text = report or _text(state.get("hypothesis")) or EMPTY_REPORT
    facts = state.get("observations") or [] if observations is None else observations
    if _has_coverage_gap(facts):
        text = _append(text, COVERAGE_NOTE)
    if _is_tunnel_question(state["question"]):
        text = _append(text, TUNNEL_DISCLAIMER)
    return text


def _has_coverage_gap(observations: list[dict[str, object]]) -> bool:
    for observation in observations:
        if not observation.get("ok"):
            return True
        if _text(observation.get("payload")).strip() in EMPTY_PAYLOADS:
            return True
    return False


def _append(text: str, note: str) -> str:
    if note in text:
        return text
    return f"{text}\n{note}".strip()


def _parse_json_object(content: str | None) -> dict[str, object]:
    if not content:
        return {}
    text = _strip_fences(content.strip())
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): value for key, value in parsed.items()}


def _strip_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
    return "\n".join(body).strip()


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
