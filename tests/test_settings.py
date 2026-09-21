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
    assert s.gigachat_base_url == "https://gigachat.devices.sberbank.ru/api/v1"
