from heimdall.application.models import ToolCall
from heimdall.application.protocols import Logger
from heimdall.domain.models import Observation

from ..state import GraphState, StateUpdate
from ..tools import Tools
from .utils import _observation_dict


class preflight:
    def __init__(self, tools: Tools, logger: Logger) -> None:
        self._tools = tools
        self._logger = logger

    async def __call__(self, state: GraphState) -> StateUpdate:
        observations = list(state.get("observations") or [])
        chunks_out: list[dict[str, object]] = []
        call_n = 0
        for chunk in state.get("retrieved_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            text = chunk.get("text")
            if not isinstance(text, str) or chunk.get("from_disk") is not True:
                chunks_out.append(dict(chunk))
                continue
            stripped, jobs = self._scan_fences(text)
            chunks_out.append({**chunk, "text": stripped})
            for kind, body_lines in jobs:
                if kind == "unclosed":
                    observations.append(
                        _observation_dict(
                            Observation(
                                source="heimdall-calls",
                                ok=False,
                                payload="",
                                error="bad heimdall-calls fence: unclosed",
                            )
                        )
                    )
                    continue
                if body_lines is None:
                    continue
                for line in body_lines:
                    parsed = self._parse_call_line(line)
                    if parsed is None:
                        observations.append(
                            _observation_dict(
                                Observation(
                                    source="heimdall-calls",
                                    ok=False,
                                    payload="",
                                    error=f"bad heimdall-calls line: {line}",
                                )
                            )
                        )
                        continue
                    name, arguments = parsed
                    call_n += 1
                    call_arguments: dict[str, object] = {
                        key: value for key, value in arguments.items()
                    }
                    try:
                        obs = await self._tools(
                            ToolCall(
                                id=f"preflight-{call_n}",
                                name=name,
                                arguments=call_arguments,
                            )
                        )
                    except Exception as exc:
                        self._logger.exception("preflight tool failed")
                        obs = Observation(
                            source=name,
                            ok=False,
                            payload="",
                            error=str(exc),
                            tool=name,
                        )
                    observations.append(_observation_dict(obs))
        return {"retrieved_chunks": chunks_out, "observations": observations}

    @staticmethod
    def _scan_fences(
        text: str,
    ) -> tuple[str, list[tuple[str, list[str] | None]]]:
        output: list[str] = []
        jobs: list[tuple[str, list[str] | None]] = []
        fragment: list[str] | None = None
        body: list[str] = []

        for line in text.splitlines():
            if fragment is None:
                if preflight._is_opener(line):
                    fragment = [line]
                    body = []
                else:
                    output.append(line)
                continue

            if preflight._is_closer(line):
                jobs.append(("run", body))
                fragment = None
                body = []
            elif preflight._is_opener(line):
                jobs.append(("unclosed", None))
                output.extend(fragment)
                fragment = [line]
                body = []
            else:
                fragment.append(line)
                stripped = line.strip()
                if stripped:
                    body.append(stripped)

        if fragment is not None:
            jobs.append(("unclosed", None))
            output.extend(fragment)

        return "\n".join(output), jobs

    @staticmethod
    def _is_opener(line: str) -> bool:
        content = line.lstrip(" \t")
        marker = "```heimdall-calls"
        return content.startswith(marker) and not content[len(marker) :].strip(" ")

    @staticmethod
    def _is_closer(line: str) -> bool:
        content = line.lstrip(" \t")
        marker = "```"
        return content.startswith(marker) and not content[len(marker) :].strip(" ")

    @staticmethod
    def _parse_call_line(line: str) -> tuple[str, dict[str, str]] | None:
        text = line.strip()
        if not text:
            return None

        index = 0
        while index < len(text) and not text[index].isspace():
            index += 1
        name = text[:index]
        if "=" in name or not name.isidentifier():
            return None

        arguments: dict[str, str] = {}
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index == len(text):
                break

            key_start = index
            while (
                index < len(text)
                and not text[index].isspace()
                and text[index] != "="
            ):
                index += 1
            key = text[key_start:index]
            if not key or index == len(text) or text[index] != "=":
                return None
            if key in arguments:
                return None
            index += 1
            if index == len(text):
                return None

            if text[index] == '"':
                index += 1
                value_start = index
                while index < len(text) and text[index] != '"':
                    index += 1
                if index == len(text):
                    return None
                value = text[value_start:index]
                index += 1
                if index < len(text) and not text[index].isspace():
                    return None
            else:
                value_start = index
                while index < len(text) and not text[index].isspace():
                    index += 1
                value = text[value_start:index]
                if not value:
                    return None
            arguments[key] = value

        return name, arguments
