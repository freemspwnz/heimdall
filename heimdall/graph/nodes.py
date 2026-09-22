import json
from dataclasses import asdict, dataclass

from langgraph.types import interrupt

from heimdall.constants import (
    DEFAULT_CONFIDENCE,
    LOG_LOOKBACK,
    MAX_OBSERVATION_LINES,
    MAX_TOOL_CALLS_PER_ROUND,
    NEVER_RESTART,
    RESTART_ALLOWLIST,
    RETRIEVE_TOP_K,
)
from heimdall.graph.prompts import (
    COVERAGE_NOTE,
    DIAGNOSE_SYSTEM,
    EMPTY_REPORT,
    INVESTIGATE_SYSTEM,
    NO_ACTION_NOTE,
    PROPOSE_SYSTEM,
    TUNNEL_DISCLAIMER,
    TUNNEL_PROMPT_RULE,
    VERIFY_SYSTEM,
)
from heimdall.graph.state import GraphState, StateUpdate
from heimdall.models import (
    Action,
    ChatMessage,
    Chunk,
    Observation,
    ToolCall,
    ToolSpec,
)
from heimdall.providers import ChatModel, Embedder, EmbeddingsUnavailable
from heimdall.rag import VectorStore
from heimdall.tools import DockerClient, LokiClient, VictoriaMetricsClient

LOKI_QUERY = "loki_query"
VM_QUERY = "vm_query"
DOCKER_PS = "docker_ps"
DOCKER_INSPECT = "docker_inspect"
DOCKER_LOGS = "docker_logs"

EMPTY_PAYLOADS = frozenset({"no streams", "no data"})
TUNNEL_MARKERS = ("туннел", "tunnel", "vpn", "sing-box", "3x-ui")
POSITIVE_ANSWERS = frozenset({"y", "yes", "да", "д"})

READ_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name=LOKI_QUERY,
        description="Прочитать логи из Loki по запросу LogQL.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "LogQL-запрос"},
                "since": {"type": "string", "description": "окно, например 15m"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=VM_QUERY,
        description="Прочитать метрики из VictoriaMetrics по запросу MetricsQL.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "MetricsQL-запрос"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=DOCKER_PS,
        description="Список контейнеров и их состояние.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolSpec(
        name=DOCKER_INSPECT,
        description="Подробное состояние одного контейнера.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "имя контейнера"},
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name=DOCKER_LOGS,
        description="Хвост логов одного контейнера.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "имя контейнера"},
                "tail": {"type": "integer", "description": "сколько строк"},
            },
            "required": ["name"],
        },
    ),
]


@dataclass(frozen=True)
class Deps:
    retriever: VectorStore
    embedder: Embedder
    chat: ChatModel
    docker: DockerClient
    loki: LokiClient
    vm: VictoriaMetricsClient


async def retrieve(state: GraphState, deps: Deps) -> StateUpdate:
    try:
        chunks = await deps.retriever.search(
            state["question"],
            deps.embedder,
            k=RETRIEVE_TOP_K,
        )
    except EmbeddingsUnavailable:
        chunks = []
    return {"retrieved_chunks": [_chunk_dict(chunk) for chunk in chunks]}


async def investigate(state: GraphState, deps: Deps) -> StateUpdate:
    observations = list(state.get("observations") or [])
    messages = [
        ChatMessage(role="system", content=_system_prompt(INVESTIGATE_SYSTEM, state)),
        ChatMessage(role="user", content=_context(state)),
    ]
    budget = MAX_TOOL_CALLS_PER_ROUND
    while budget > 0:
        result = await deps.chat.complete(messages, tools=READ_TOOLS)
        if not result.tool_calls:
            break
        calls = result.tool_calls[:budget]
        budget -= len(calls)
        messages.append(
            ChatMessage(
                role="assistant",
                content=result.content or "",
                tool_calls=calls,
            )
        )
        for call in calls:
            observation = await _run_tool(deps, call)
            observations.append(_observation_dict(observation))
            messages.append(
                ChatMessage(
                    role="tool",
                    content=_observation_text(observation),
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
    rounds = state.get("investigate_rounds") or 0
    return {"investigate_rounds": rounds + 1, "observations": observations}


async def diagnose(state: GraphState, deps: Deps) -> StateUpdate:
    result = await deps.chat.complete(
        [
            ChatMessage(role="system", content=_system_prompt(DIAGNOSE_SYSTEM, state)),
            ChatMessage(role="user", content=_context(state)),
        ]
    )
    data = _parse_json_object(result.content)
    report = _text(data.get("report"))
    unknown = _text(data.get("unknown"))
    if unknown:
        report = _append(report, f"Не проверено: {unknown}")  # noqa: RUF001
    return {
        "hypothesis": _text(data.get("hypothesis")) or None,
        "confidence": _confidence(data.get("confidence")),
        "report": report or None,
    }


async def propose(state: GraphState, deps: Deps) -> StateUpdate:
    result = await deps.chat.complete(
        [
            ChatMessage(role="system", content=_system_prompt(PROPOSE_SYSTEM, state)),
            ChatMessage(role="user", content=_context(state)),
        ]
    )
    data = _parse_json_object(result.content)
    report = _text(data.get("report")) or _text(state.get("report"))
    action = _parse_action(data.get("action"))
    if action is None:
        return {"proposed_action": None, "report": _final_report(state, report)}
    return {"proposed_action": asdict(action), "report": report or None}


async def confirm(state: GraphState) -> StateUpdate:
    answer = interrupt({"proposed_action": state.get("proposed_action")})
    if _decision(answer) == "yes":
        return {"human_decision": "yes"}
    report = _append(_text(state.get("report")), NO_ACTION_NOTE)
    return {"human_decision": "no", "report": _final_report(state, report)}


async def execute(state: GraphState, deps: Deps) -> StateUpdate:
    action = state.get("proposed_action")
    if state.get("human_decision") != "yes" or action is None:
        return {}
    observation = await deps.docker.restart(_text(action.get("target")))
    return {"execution_result": _observation_dict(observation)}


async def verify(state: GraphState, deps: Deps) -> StateUpdate:
    action = state.get("proposed_action") or {}
    target = _text(action.get("target"))
    observations = list(state.get("observations") or [])
    if target:
        observations.append(_observation_dict(await deps.docker.inspect(target)))
        observations.append(_observation_dict(await deps.docker.logs(target)))
    result = await deps.chat.complete(
        [
            ChatMessage(role="system", content=_system_prompt(VERIFY_SYSTEM, state)),
            ChatMessage(role="user", content=_verify_context(state, observations)),
        ]
    )
    report = _text(result.content) or _text(state.get("report"))
    return {
        "observations": observations,
        "report": _final_report(state, report, observations),
    }


async def _run_tool(deps: Deps, call: ToolCall) -> Observation:
    arguments = call.arguments
    if call.name == LOKI_QUERY:
        since = _text(arguments.get("since")) or LOG_LOOKBACK
        return await deps.loki.query(_text(arguments.get("query")), since=since)
    if call.name == VM_QUERY:
        return await deps.vm.query(_text(arguments.get("query")))
    if call.name == DOCKER_PS:
        return await deps.docker.ps()
    if call.name == DOCKER_INSPECT:
        return await deps.docker.inspect(_text(arguments.get("name")))
    if call.name == DOCKER_LOGS:
        tail = _tail(arguments.get("tail"))
        return await deps.docker.logs(_text(arguments.get("name")), tail=tail)
    return Observation(
        source=call.name,
        ok=False,
        payload="",
        error=f"unknown tool: {call.name}",
    )


def _chunk_dict(chunk: Chunk) -> dict[str, object]:
    return asdict(chunk)


def _observation_dict(observation: Observation) -> dict[str, object]:
    return asdict(observation)


def _observation_text(observation: Observation) -> str:
    if observation.ok:
        return observation.payload
    return f"ошибка: {observation.error}"


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


def _verify_context(state: GraphState, observations: list[dict[str, object]]) -> str:
    context = _context(state, observations)
    execution = state.get("execution_result")
    if execution is None:
        return context
    result = _facts_block([execution])
    return f"{context}\n\nРезультат команды:\n{result}"  # noqa: RUF001


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


def _parse_action(value: object) -> Action | None:
    if not isinstance(value, dict):
        return None
    tool = _text(value.get("tool")) or "restart"
    if tool != "restart":
        return None
    target = _text(value.get("target"))
    if target not in RESTART_ALLOWLIST or target in NEVER_RESTART:
        return None
    return Action(
        tool=tool,
        target=target,
        reason=_text(value.get("reason")),
        risk=_text(value.get("risk")),
    )


def _decision(answer: object) -> str:
    if isinstance(answer, str) and answer.strip().lower() in POSITIVE_ANSWERS:
        return "yes"
    return "no"


def _confidence(value: object) -> float:
    if isinstance(value, bool):
        return DEFAULT_CONFIDENCE
    if isinstance(value, int | float):
        candidate = float(value)
    elif isinstance(value, str):
        try:
            candidate = float(value.strip())
        except ValueError:
            return DEFAULT_CONFIDENCE
    else:
        return DEFAULT_CONFIDENCE
    if 0.0 <= candidate <= 1.0:
        return candidate
    return DEFAULT_CONFIDENCE


def _tail(value: object) -> int:
    if isinstance(value, bool):
        return MAX_OBSERVATION_LINES
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return MAX_OBSERVATION_LINES


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
