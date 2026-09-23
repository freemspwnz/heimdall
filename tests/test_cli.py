import asyncio
from pathlib import Path
from typing import Any

import pytest
from heimdall.cli import AppDeps, main
from heimdall.models import ChatMessage, ChatResult, Chunk, ToolSpec
from heimdall.providers import (
    Embedder,
    EmbeddingsUnavailable,
    FakeEmbedder,
)
from heimdall.rag import InMemoryVectorStore
from langgraph.checkpoint.memory import MemorySaver


class BrokenEmbedder:
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del texts, query
        raise EmbeddingsUnavailable("503 embeddings down")


class BrokenStore:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def upsert(self, chunks: list[Chunk], embedder: Embedder) -> None:
        raise self._error

    async def search(
        self,
        query: str,
        embedder: Embedder,
        k: int = 5,
    ) -> list[Chunk]:
        raise self._error


class ExplodingDeps:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aenter__(self) -> AppDeps:
        raise self._error

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def patch_ingest_production_deps(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(
        "heimdall.cli._ingest_production_deps", lambda: ExplodingDeps(error)
    )


class UnusedChat:
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        del messages, tools
        raise AssertionError("chat should not run in ingest tests")


def make_deps(
    *,
    store: Any | None = None,
    embedder: Any | None = None,
    knowledge_dir: Path = Path("docs/knowledge"),
) -> AppDeps:
    return AppDeps(
        store=store if store is not None else InMemoryVectorStore(),
        embedder=embedder if embedder is not None else FakeEmbedder(),
        chat=UnusedChat(),  # type: ignore[arg-type]
        docker=object(),  # type: ignore[arg-type]
        loki=object(),  # type: ignore[arg-type]
        vm=object(),  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
        knowledge_dir=knowledge_dir,
    )


def write_knowledge(root: Path) -> Path:
    knowledge = root / "knowledge"
    (knowledge / "runbooks").mkdir(parents=True)
    (knowledge / "inventory.md").write_text(
        "## Хост\nОдин docker-хост.\n",  # noqa: RUF001
        encoding="utf-8",
    )
    (knowledge / "runbooks" / "postgres.md").write_text(
        "## Postgres\nРестарт рвёт активные соединения.\n",  # noqa: RUF001
        encoding="utf-8",
    )
    return knowledge


def test_ingest_upserts_the_knowledge_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = InMemoryVectorStore()
    deps = make_deps(
        store=store,
        knowledge_dir=write_knowledge(tmp_path),
    )

    code = main(["ingest"], deps=deps)

    assert code == 0
    found = asyncio.run(store.search("postgres", FakeEmbedder()))
    assert [chunk.source for chunk in found] == [
        "runbooks/postgres.md",
        "inventory.md",
    ]
    assert "2" in capsys.readouterr().out


def test_ingest_reports_unavailable_embeddings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deps = make_deps(
        embedder=BrokenEmbedder(),
        knowledge_dir=write_knowledge(tmp_path),
    )

    code = main(["ingest"], deps=deps)

    assert code == 1
    assert "эмбеддинги недоступны" in capsys.readouterr().out


def test_ingest_reports_an_unreachable_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = BrokenStore(ConnectionRefusedError("postgres refused the connection"))
    deps = make_deps(
        store=store,
        knowledge_dir=write_knowledge(tmp_path),
    )

    code = main(["ingest"], deps=deps)

    assert code != 0
    assert "postgres refused the connection" in capsys.readouterr().out


def test_ingest_reports_a_broken_production_setup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    patch_ingest_production_deps(monkeypatch, OSError("unable to open database file"))

    code = main(["ingest"])

    assert code == 1
    assert "unable to open database file" in capsys.readouterr().err


def test_ingest_uses_ingest_production_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Marker:
        async def __aenter__(self) -> AppDeps:
            seen.append("ingest")
            raise RuntimeError("stop-after-wiring")

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr("heimdall.cli._ingest_production_deps", lambda: Marker())
    monkeypatch.setattr(
        "heimdall.cli._production_deps",
        lambda: (_ for _ in ()).throw(AssertionError("ask deps used for ingest")),
    )

    code = main(["ingest"])

    assert code == 1
    assert seen == ["ingest"]


def test_docker_connector_requires_unix_socket() -> None:
    from heimdall.cli import _docker_connector

    with pytest.raises(ValueError, match="unix://"):
        _docker_connector("tcp://127.0.0.1:2375")


def test_ask_subcommand_removed() -> None:
    assert main(["ask", "ping"]) != 0


def test_bare_heimdall_runs_client_repl(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    async def fake_repl(base_url: str, **kwargs: object) -> int:
        del kwargs
        called["url"] = base_url
        return 0

    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setenv(
        "POSTGRES_DSN", "postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall"
    )
    monkeypatch.setattr("heimdall.cli.run_repl", fake_repl)
    assert main([]) == 0
    assert called["url"] == "http://127.0.0.1:8080"


def test_cli_subcommand_runs_client_repl(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    async def fake_repl(base_url: str, **kwargs: object) -> int:
        del kwargs
        called["url"] = base_url
        return 0

    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setenv(
        "POSTGRES_DSN", "postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall"
    )
    monkeypatch.setattr("heimdall.cli.run_repl", fake_repl)
    assert main(["cli"]) == 0
    assert called["url"] == "http://127.0.0.1:8080"


def test_main_with_an_unknown_command_fails() -> None:
    assert main(["deploy"]) != 0


def test_serve_command_is_registered() -> None:
    from heimdall.cli import _parser

    parser = _parser()
    args = parser.parse_args(["serve"])
    assert args.command == "serve"


def test_main_serve_invokes_run_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {}

    async def fake_run_serve() -> int:
        called["yes"] = True
        return 0

    monkeypatch.setattr("heimdall.cli.run_serve", fake_run_serve)
    assert main(["serve"]) == 0
    assert called["yes"]
