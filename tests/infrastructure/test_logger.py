import logging
from importlib.metadata import version
from pathlib import Path

import pytest
from heimdall.infrastructure.logger import get_logger
from heimdall.infrastructure.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gigachat_credentials": "super-secret-token",
        "postgres_dsn": "postgresql://heimdall:db-secret@127.0.0.1:5432/heimdall",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_get_logger_masks_settings_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    settings = _settings()
    log = get_logger(settings)
    log.info("cred {} dsn {}", settings.gigachat_credentials, settings.postgres_dsn)
    written = capsys.readouterr().out
    assert "super-secret-token" not in written
    assert "db-secret" not in written
    assert "****" in written
    assert "heimdall" in written
    assert "wednesday" not in written
    assert version("heimdall") in written
    assert "INFO" in written
    assert not any(
        line.lstrip().startswith("{") for line in written.splitlines() if line
    )
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_log_level_comes_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
    log = get_logger(_settings(log_level="ERROR"))
    log.info("info-hidden")
    log.error("error-visible")
    written = capsys.readouterr().out
    assert "info-hidden" not in written
    assert "error-visible" in written


def test_loguru_and_get_logger_stay_inside_the_composition_root() -> None:
    root = Path("heimdall")
    logger_pkg = root / "infrastructure" / "logger"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path == logger_pkg or logger_pkg in path.parents:
            continue
        assert "from loguru" not in text
        assert "import loguru" not in text
        if path != root / "infrastructure" / "deps.py":
            assert "get_logger" not in text
