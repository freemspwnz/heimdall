from heimdall.settings import Settings


def test_settings_read_env(monkeypatch) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret-key")
    monkeypatch.setenv(
        "POSTGRES_DSN", "postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall"
    )
    monkeypatch.setenv("LOKI_URL", "http://127.0.0.1:3100")
    monkeypatch.delenv("VICTORIAMETRICS_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.gigachat_credentials == "secret-key"
    assert s.loki_url == "http://127.0.0.1:3100"
    assert s.victoriametrics_url == "http://127.0.0.1:8428"
    assert s.docker_host == "unix:///var/run/docker.sock"
    assert s.gigachat_base_url == "https://api.giga.chat/v1"
    assert s.embedder == "local"
    assert s.local_embedder_model == "intfloat/multilingual-e5-base"


def test_settings_gigachat_ultra_defaults(monkeypatch) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret-key")
    monkeypatch.setenv(
        "POSTGRES_DSN", "postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall"
    )
    monkeypatch.delenv("GIGACHAT_BASE_URL", raising=False)
    monkeypatch.delenv("GIGACHAT_CHAT_MODEL", raising=False)
    s = Settings(_env_file=None)
    assert s.gigachat_base_url == "https://api.giga.chat/v1"
    assert s.gigachat_chat_model == "GigaChat-3-Ultra"


def test_settings_optional_paths_and_oauth_defaults(monkeypatch) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret-key")
    monkeypatch.setenv(
        "POSTGRES_DSN", "postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall"
    )
    monkeypatch.delenv("GIGACHAT_OAUTH_URL", raising=False)
    monkeypatch.delenv("GIGACHAT_SCOPE", raising=False)
    monkeypatch.delenv("CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("KNOWLEDGE_DIR", raising=False)
    s = Settings(_env_file=None)
    assert s.gigachat_oauth_url.endswith("/oauth")
    assert s.gigachat_scope == "GIGACHAT_API_PERS"
    assert s.checkpoint_path == "heimdall-checkpoints.sqlite"
    assert s.knowledge_dir.as_posix() == "docs/knowledge"
