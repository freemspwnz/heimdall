from heimdall.application.models import ChatMessage
from heimdall.application.protocols import ChatModel, Logger
from heimdall.infrastructure.constants import DEFAULT_QUESTION_KIND, QUESTION_KINDS

from ..prompts import CLASSIFY_SYSTEM
from ..state import GraphState, StateUpdate
from .utils import _parse_json_object, _text


class classify:
    def __init__(self, chat: ChatModel, logger: Logger) -> None:
        self._chat = chat
        self._logger = logger

    async def __call__(self, state: GraphState) -> StateUpdate:
        catalog = _catalog()
        names = {name for name, _block in catalog}
        kind = DEFAULT_QUESTION_KIND
        runbooks: list[str] = []
        try:
            result = await self._chat.complete(
                [
                    ChatMessage(role="system", content=CLASSIFY_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=_user(state["question"], catalog),
                    ),
                ],
                node="classify",
            )
        except Exception:
            self._logger.exception("classify failed; defaulting to diagnose")
        else:
            parsed = _parse_json_object(result.content)
            selected = _selected(parsed.get("runbooks"), names)
            if selected is None:
                kind = DEFAULT_QUESTION_KIND
                runbooks = []
            else:
                raw_kind = _text(parsed.get("question_kind"))
                if raw_kind in QUESTION_KINDS:
                    kind = raw_kind
                runbooks = selected
        self._logger.info("question_kind={}", kind)
        return {"question_kind": kind, "runbooks": runbooks}


def _catalog() -> list[tuple[str, str]]:
    from .. import paths

    directory = paths.RUNBOOKS_DIR
    try:
        candidates = sorted(
            (path for path in directory.glob("*.md") if path.is_file()),
            key=lambda path: path.name,
        )
    except OSError:
        return []
    entries: list[tuple[str, str]] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        entries.append((path.name, _catalog_block(path.name, text)))
    return entries


def _catalog_block(name: str, text: str) -> str:
    title: str | None = None
    section: list[str] | None = None
    for line in text.splitlines():
        if title is None and line.startswith("# "):
            title = line
            continue
        if line.startswith("## "):
            if section is None:
                section = [line]
                continue
            break
        if section is not None:
            section.append(line)
    lines = [name]
    if title is not None:
        lines.append(title)
    if section is not None:
        lines.append("\n".join(section).strip())
    return "\n".join(lines)


def _user(question: str, catalog: list[tuple[str, str]]) -> str:
    body = "\n\n".join(block for _name, block in catalog)
    return f"Вопрос: {question}\n\nКаталог:\n\n{body}"  # noqa: RUF001


def _selected(raw: object, names: set[str]) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    chosen: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or item not in names or item in seen:
            continue
        seen.add(item)
        chosen.append(item)
    return chosen
