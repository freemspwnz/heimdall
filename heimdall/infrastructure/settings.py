import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    heimdall_listen: str = "0.0.0.0:8080"
    heimdall_url: str = "http://127.0.0.1:8080"
    log_level: str = "INFO"

    @staticmethod
    def resolve_heimdall_url() -> str:
        """Client-side URL only — does not require GigaChat/Postgres credentials."""
        load_dotenv()
        return os.environ.get("HEIMDALL_URL", "http://127.0.0.1:8080")

    @staticmethod
    def parse_listen(listen: str) -> tuple[str, int]:
        host, _, port_s = listen.rpartition(":")
        return host, int(port_s)

    @field_validator("docker_host")
    @classmethod
    def validate_docker_host(cls, v: str) -> str:
        if not v.startswith("unix://"):
            raise ValueError("DOCKER_HOST must be a unix:// socket")
        return v

    @property
    def docker_socket_path(self) -> str:
        return self.docker_host.removeprefix("unix://")
