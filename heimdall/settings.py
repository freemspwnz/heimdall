import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_HEIMDALL_URL = "http://127.0.0.1:8080"
DEFAULT_HEIMDALL_LISTEN = "0.0.0.0:8080"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gigachat_credentials: str
    gigachat_base_url: str = "https://api.giga.chat/v1"
    gigachat_chat_model: str = "GigaChat-3-Ultra"
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_verify_ssl: bool = True
    loki_url: str = "http://127.0.0.1:3100"
    victoriametrics_url: str = "http://127.0.0.1:8428"
    docker_host: str = "unix:///var/run/docker.sock"
    postgres_dsn: str
    checkpoint_path: str = "heimdall-checkpoints.sqlite"
    knowledge_dir: Path = Path("docs/knowledge")
    embedder: Literal["local", "gigachat"] = "local"
    local_embedder_model: str = "intfloat/multilingual-e5-base"
    heimdall_listen: str = DEFAULT_HEIMDALL_LISTEN
    heimdall_url: str = DEFAULT_HEIMDALL_URL


def resolve_heimdall_url() -> str:
    """Client-side URL only — does not require GigaChat/Postgres credentials."""
    load_dotenv()
    return os.environ.get("HEIMDALL_URL", DEFAULT_HEIMDALL_URL)
