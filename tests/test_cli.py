import sys

import pytest
from heimdall.__main__ import main


def test_bare_invocation_prints_help_and_fails() -> None:
    assert main([]) == 1


def test_unknown_command_fails() -> None:
    assert main(["deploy"]) != 0


def test_ask_subcommand_is_not_a_command() -> None:
    assert main(["ask", "ping"]) != 0


def test_cli_subcommand_runs_client(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {}

    async def fake_cli() -> int:
        called["cli"] = True
        return 0

    monkeypatch.setattr("heimdall.__main__.cli", fake_cli)
    assert main(["cli"]) == 0
    assert called["cli"]


def test_serve_subcommand_runs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {}

    async def fake_serve() -> int:
        called["serve"] = True
        return 0

    monkeypatch.setattr("heimdall.__main__.serve", fake_serve)
    assert main(["serve"]) == 0
    assert called["serve"]


def test_serve_executable_without_args_starts_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, bool] = {}

    async def fake_serve() -> int:
        called["serve"] = True
        return 0

    monkeypatch.setattr(sys, "argv", ["/app/.venv/bin/serve"])
    monkeypatch.setattr("heimdall.__main__.serve", fake_serve)
    assert main() == 0
    assert called["serve"]


def test_cli_executable_without_args_starts_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, bool] = {}

    async def fake_cli() -> int:
        called["cli"] = True
        return 0

    monkeypatch.setattr(sys, "argv", ["/app/.venv/bin/cli"])
    monkeypatch.setattr("heimdall.__main__.cli", fake_cli)
    assert main() == 0
    assert called["cli"]


def test_serve_help_does_not_start_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, bool] = {}

    async def fake_serve() -> int:
        called["serve"] = True
        return 0

    monkeypatch.setattr(sys, "argv", ["/app/.venv/bin/serve", "--help"])
    monkeypatch.setattr("heimdall.__main__.serve", fake_serve)
    assert main() == 0
    assert called == {}
