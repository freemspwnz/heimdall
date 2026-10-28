import json
from dataclasses import asdict

from heimdall.domain.models import Observation

from ..prompts import COVERAGE_NOTE, EMPTY_REPORT
from ..state import GraphState

EMPTY_PAYLOADS = frozenset({"no streams", "no data"})


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
        header = f"[{source}] {status}"
        call = _call_line(observation)
        payload = _text(observation.get("payload"))
        if call:
            blocks.append(f"{header}\n{call}\n{payload}")
        else:
            blocks.append(f"{header}\n{payload}")
    return "\n\n".join(blocks)


def _call_line(observation: dict[str, object]) -> str:
    parts: list[str] = []
    tool = _text(observation.get("tool"))
    target = _text(observation.get("target"))
    since = _text(observation.get("since"))
    query = _text(observation.get("query"))
    if tool:
        parts.append(tool)
    if target:
        parts.append(f"target={target}")
    if since:
        parts.append(f"since={since}")
    if query:
        parts.append(f"query={query}")
    return " ".join(parts)


def _final_report(
    state: GraphState,
    report: str,
    observations: list[dict[str, object]] | None = None,
) -> str:
    text = report or _text(state.get("hypothesis")) or EMPTY_REPORT
    facts = state.get("observations") or [] if observations is None else observations
    if _has_coverage_gap(facts):
        text = _append(text, COVERAGE_NOTE)
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
