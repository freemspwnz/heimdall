from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from heimdall.providers import (
    ChatModel,
    Embedder,
    GigaChatChatModel,
    GigaChatEmbedder,
    LocalEmbedder,
)
from heimdall.rag import PgVectorStore, VectorStore
from heimdall.settings import Settings
from heimdall.tools import DockerClient, LokiClient, VictoriaMetricsClient

_UNIX_PREFIX = "unix://"


@dataclass(frozen=True)
class AppDeps:
    store: VectorStore
    embedder: Embedder
    chat: ChatModel
    docker: DockerClient
    loki: LokiClient
    vm: VictoriaMetricsClient
    checkpointer: BaseCheckpointSaver[Any]
    knowledge_dir: Path


def parse_listen(listen: str) -> tuple[str, int]:
    host, _, port_s = listen.rpartition(":")
    return host, int(port_s)


def docker_connector(docker_host: str) -> aiohttp.BaseConnector:
    if not docker_host.startswith(_UNIX_PREFIX):
        msg = f"DOCKER_HOST must be a unix:// socket, got {docker_host!r}"
        raise ValueError(msg)
    return aiohttp.UnixConnector(path=docker_host.removeprefix(_UNIX_PREFIX))


def make_embedder(settings: Settings, http: aiohttp.ClientSession) -> Embedder:
    if settings.embedder == "gigachat":
        return GigaChatEmbedder(settings, http)
    return LocalEmbedder(settings.local_embedder_model)


def core_deps(
    settings: Settings,
    http: aiohttp.ClientSession,
    docker_http: aiohttp.ClientSession,
    checkpointer: BaseCheckpointSaver[Any],
) -> AppDeps:
    return AppDeps(
        store=PgVectorStore(settings.postgres_dsn),
        embedder=make_embedder(settings, http),
        chat=GigaChatChatModel(settings, http),
        docker=DockerClient(settings.docker_host, docker_http),
        loki=LokiClient(settings.loki_url, http),
        vm=VictoriaMetricsClient(settings.victoriametrics_url, http),
        checkpointer=checkpointer,
        knowledge_dir=settings.knowledge_dir,
    )


@asynccontextmanager
async def production_deps(
    settings: Settings | None = None,
) -> AsyncIterator[AppDeps]:
    resolved = settings if settings is not None else Settings()  # type: ignore[call-arg]
    async with (
        aiohttp.ClientSession() as http,
        aiohttp.ClientSession(
            connector=docker_connector(resolved.docker_host)
        ) as docker_http,
        AsyncSqliteSaver.from_conn_string(resolved.checkpoint_path) as checkpointer,
    ):
        yield core_deps(resolved, http, docker_http, checkpointer)


@asynccontextmanager
async def ingest_production_deps(
    settings: Settings | None = None,
) -> AsyncIterator[AppDeps]:
    resolved = settings if settings is not None else Settings()  # type: ignore[call-arg]
    async with (
        aiohttp.ClientSession() as http,
        aiohttp.ClientSession(
            connector=docker_connector(resolved.docker_host)
        ) as docker_http,
    ):
        yield core_deps(resolved, http, docker_http, MemorySaver())
