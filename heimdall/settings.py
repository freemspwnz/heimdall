from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gigachat_credentials: str
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_verify_ssl: bool = True
    loki_url: str = "http://127.0.0.1:3100"
    victoriametrics_url: str = "http://127.0.0.1:8428"
    docker_host: str = "unix:///var/run/docker.sock"
    postgres_dsn: str
    checkpoint_path: str = "heimdall-checkpoints.sqlite"
    knowledge_dir: Path = Path("docs/knowledge")
