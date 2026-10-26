from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Self

import aiohttp
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from heimdall.application.protocols import (
    ChatModel,
    Docker,
    Embedder,
    Loki,
    VectorStore,
    VictoriaMetrics,
)

from .aiohttp import DockerClient, GigaChatClient, LokiClient, VictoriaMetricsClient
from .embedders import GigaChatEmbedder, LocalEmbedder, load_sentence_transformer
from .llms import GigaChatChatModel
from .settings import Settings
from .store import PgVectorStore


@dataclass(frozen=True)
class GraphDeps:
    retriever: VectorStore
    embedder: Embedder
    chat: ChatModel
    docker: Docker
    loki: Loki
    vm: VictoriaMetrics


class Container:
    def __init__(
        self,
        settings: Settings,
        http: aiohttp.ClientSession,
        docker_http: aiohttp.ClientSession,
        checkpointer: AsyncSqliteSaver,
    ) -> None:
        self._settings = settings
        self._http = http
        self._docker_http = docker_http
        self._checkpointer = checkpointer

    @classmethod
    @asynccontextmanager
    async def open(cls, settings: Settings) -> AsyncIterator[Self]:
        async with AsyncExitStack() as stack:
            http = await stack.enter_async_context(aiohttp.ClientSession())
            docker_http = await stack.enter_async_context(
                aiohttp.ClientSession(
                    connector=aiohttp.UnixConnector(
                        path=settings.docker_socket_path,
                    )
                )
            )
            checkpointer = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(settings.checkpoint_path)
            )
            yield cls(settings, http, docker_http, checkpointer)

    @cached_property
    def store(self) -> VectorStore:
        return PgVectorStore(self._settings.postgres_dsn)

    @cached_property
    def embedder(self) -> Embedder:
        if self._settings.embedder == "gigachat":
            return GigaChatEmbedder(self._settings, self._gigachat)
        return LocalEmbedder(
            model=load_sentence_transformer(self._settings.local_embedder_model)
        )

    @cached_property
    def chat(self) -> ChatModel:
        return GigaChatChatModel(self._settings, self._gigachat)

    @cached_property
    def docker(self) -> Docker:
        return DockerClient(self._settings.docker_host, self._docker_http)

    @cached_property
    def loki(self) -> Loki:
        return LokiClient(self._settings.loki_url, self._http)

    @cached_property
    def vm(self) -> VictoriaMetrics:
        return VictoriaMetricsClient(self._settings.victoriametrics_url, self._http)

    @property
    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        return self._checkpointer

    @cached_property
    def knowledge_dir(self) -> Path:
        return Path(self._settings.knowledge_dir)

    @cached_property
    def graph_deps(self) -> GraphDeps:
        return GraphDeps(
            retriever=self.store,
            embedder=self.embedder,
            chat=self.chat,
            docker=self.docker,
            loki=self.loki,
            vm=self.vm,
        )

    @cached_property
    def _gigachat(self) -> GigaChatClient:
        return GigaChatClient(self._settings, self._http)
