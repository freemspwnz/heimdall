import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from heimdall.models import ChatMessage, ToolCall, ToolSpec
from heimdall.providers import (
    ChatUnavailable,
    EmbeddingsUnavailable,
    FakeChatModel,
    FakeEmbedder,
    GigaChatChatModel,
    GigaChatEmbedder,
    ScriptedTurn,
)
from heimdall.settings import Settings


def _settings() -> Settings:
    return Settings(
        gigachat_credentials="dGVzdA==",
        postgres_dsn="postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall",
        _env_file=None,
    )


def _response(status: int, body: dict[str, object] | str) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    payload = body if isinstance(body, str) else json.dumps(body)
    resp.text = AsyncMock(return_value=payload)
    if isinstance(body, dict):
        resp.json = AsyncMock(return_value=body)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


def _session(posts: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.post = MagicMock(side_effect=posts)
    return session


@pytest.mark.asyncio
async def test_fake_chat_model_pops_tool_calls_then_content() -> None:
    inspect = ToolCall(
        id="call_1",
        name="docker_inspect",
        arguments={"target": "postgres"},
    )
    tools = [
        ToolSpec(
            name="docker_inspect",
            description="inspect a container",
            parameters={"type": "object"},
        )
    ]
    model = FakeChatModel(
        [
            ScriptedTurn(tool_calls=[inspect]),
            ScriptedTurn(content="container is unhealthy"),
        ]
    )
    messages = [ChatMessage(role="user", content="What about postgres?")]
    first = await model.complete(messages, tools=tools)
    assert first.tool_calls == [inspect]
    second = await model.complete(messages)
    assert second.content == "container is unhealthy"
    assert second.tool_calls == []
    assert model.calls[0]["tools"] == tools
    assert model.calls[0]["tools"] is not tools
    assert model.calls[1]["tools"] is None


@pytest.mark.asyncio
async def test_gigachat_chat_parses_tool_calls_after_oauth() -> None:
    settings = _settings()
    oauth = _response(200, {"access_token": "tok-1"})
    chat = _response(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "role": "assistant",
                        "function_call": {
                            "name": "docker_inspect",
                            "arguments": {"name": "postgres"},
                        },
                        "finish_reason": "function_call",
                    }
                }
            ]
        },
    )
    chat_again = _response(
        200,
        {"choices": [{"message": {"content": "ok"}}]},
    )
    session = _session([oauth, chat, chat_again])
    model = GigaChatChatModel(settings, session)
    tools = [
        ToolSpec(
            name="docker_inspect",
            description="inspect a container",
            parameters={"type": "object", "properties": {}},
        )
    ]
    result = await model.complete(
        [ChatMessage(role="user", content="q")],
        tools=tools,
    )
    assert result.tool_calls[0].name == "docker_inspect"
    assert result.tool_calls[0].arguments == {"name": "postgres"}
    assert result.tool_calls[0].id
    oauth_url = session.post.call_args_list[0].args[0]
    chat_url = session.post.call_args_list[1].args[0]
    assert oauth_url == settings.gigachat_oauth_url
    assert "/oauth" in oauth_url
    assert chat_url == f"{settings.gigachat_base_url}/chat/completions"
    oauth_kwargs = session.post.call_args_list[0].kwargs
    assert oauth_kwargs["headers"]["Authorization"] == "Basic dGVzdA=="
    assert "RqUID" in oauth_kwargs["headers"]
    data = oauth_kwargs["data"]
    if isinstance(data, dict):
        assert data["scope"] == settings.gigachat_scope
    else:
        assert "scope=GIGACHAT_API_PERS" in str(data)
    chat_kwargs = session.post.call_args_list[1].kwargs
    assert chat_kwargs["headers"]["Authorization"] == "Bearer tok-1"
    payload = chat_kwargs["json"]
    assert payload["model"] == settings.gigachat_chat_model
    assert "tools" not in payload
    assert payload["function_call"] == "auto"
    assert payload["functions"] == [
        {
            "name": "docker_inspect",
            "description": "inspect a container",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    await model.complete([ChatMessage(role="user", content="again")])
    assert session.post.call_count == 3
    third_url = session.post.call_args_list[2].args[0]
    assert third_url.endswith("/chat/completions")
    third_payload = session.post.call_args_list[2].kwargs["json"]
    assert third_payload["model"] == settings.gigachat_chat_model
    assert "functions" not in third_payload
    assert "function_call" not in third_payload


@pytest.mark.asyncio
async def test_gigachat_serializes_investigate_history_as_native_functions() -> None:
    settings = _settings()
    session = _session(
        [
            _response(200, {"access_token": "tok-1"}),
            _response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    model = GigaChatChatModel(settings, session)
    messages = [
        ChatMessage(role="user", content="q"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="docker_inspect",
                    arguments={"name": "postgres"},
                )
            ],
        ),
        ChatMessage(
            role="tool",
            content="ok payload",
            tool_call_id="call_1",
            name="docker_inspect",
        ),
    ]
    await model.complete(messages)
    wire = session.post.call_args_list[1].kwargs["json"]["messages"]
    assert wire[1]["role"] == "assistant"
    assert wire[1]["function_call"] == {
        "name": "docker_inspect",
        "arguments": {"name": "postgres"},
    }
    assert "tool_calls" not in wire[1]
    assert wire[2] == {
        "role": "function",
        "name": "docker_inspect",
        "content": json.dumps({"result": "ok payload"}, ensure_ascii=False),
    }


@pytest.mark.asyncio
async def test_gigachat_chat_503_raises_chat_unavailable() -> None:
    settings = _settings()
    session = _session(
        [
            _response(200, {"access_token": "tok-1"}),
            _response(503, "busy"),
        ]
    )
    model = GigaChatChatModel(settings, session)
    with pytest.raises(ChatUnavailable):
        await model.complete([ChatMessage(role="user", content="q")])
    assert session.post.call_args_list[1].args[0].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_gigachat_oauth_failure_raises_chat_unavailable() -> None:
    settings = _settings()
    session = _session([_response(401, "nope")])
    model = GigaChatChatModel(settings, session)
    with pytest.raises(ChatUnavailable):
        await model.complete([ChatMessage(role="user", content="q")])
    assert "/oauth" in session.post.call_args.args[0]


@pytest.mark.asyncio
async def test_gigachat_embeddings_200_returns_vectors() -> None:
    settings = _settings()
    session = _session(
        [
            _response(200, {"access_token": "tok-emb"}),
            _response(
                200,
                {
                    "data": [
                        {"embedding": [0.1, 0.2]},
                        {"embedding": [0.3, 0.4]},
                    ]
                },
            ),
            _response(200, {"data": [{"embedding": [0.5]}]}),
        ]
    )
    embedder = GigaChatEmbedder(settings, session)
    vectors = await embedder.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    embed_url = session.post.call_args_list[1].args[0]
    assert embed_url == f"{settings.gigachat_base_url}/embeddings"
    assert "/embeddings" in embed_url
    assert session.post.call_args_list[1].kwargs["json"] == {
        "model": "Embeddings",
        "input": ["a", "b"],
    }
    assert session.post.call_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer tok-emb"
    )
    await embedder.embed(["c"])
    assert session.post.call_count == 3
    assert session.post.call_args_list[2].kwargs["json"]["model"] == "Embeddings"


@pytest.mark.asyncio
async def test_gigachat_embeddings_500_raises_unavailable() -> None:
    settings = _settings()
    session = _session(
        [
            _response(200, {"access_token": "tok-emb"}),
            _response(500, "boom"),
        ]
    )
    embedder = GigaChatEmbedder(settings, session)
    with pytest.raises(EmbeddingsUnavailable):
        await embedder.embed(["x"])


@pytest.mark.asyncio
async def test_gigachat_verify_ssl_false_passes_ssl_false() -> None:
    settings = Settings(
        gigachat_credentials="dGVzdA==",
        postgres_dsn="postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall",
        gigachat_verify_ssl=False,
        _env_file=None,
    )
    session = _session(
        [
            _response(200, {"access_token": "tok-1"}),
            _response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    model = GigaChatChatModel(settings, session)
    await model.complete([ChatMessage(role="user", content="q")])
    for call in session.post.call_args_list:
        assert call.kwargs["ssl"] is False


@pytest.mark.asyncio
async def test_gigachat_verify_ssl_true_passes_ssl_true() -> None:
    settings = Settings(
        gigachat_credentials="dGVzdA==",
        postgres_dsn="postgresql://heimdall:heimdall@127.0.0.1:5432/heimdall",
        gigachat_verify_ssl=True,
        _env_file=None,
    )
    session = _session(
        [
            _response(200, {"access_token": "tok-1"}),
            _response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    model = GigaChatChatModel(settings, session)
    await model.complete([ChatMessage(role="user", content="q")])
    for call in session.post.call_args_list:
        assert call.kwargs["ssl"] is True


@pytest.mark.asyncio
async def test_fake_chat_model_stores_message_copies() -> None:
    model = FakeChatModel([ScriptedTurn(content="ok")])
    messages = [ChatMessage(role="user", content="q")]
    await model.complete(messages)
    messages.append(ChatMessage(role="assistant", content="later"))
    stored = model.calls[0]["messages"]
    assert isinstance(stored, list)
    assert len(stored) == 1
    assert stored[0].content == "q"


@pytest.mark.asyncio
async def test_fake_embedder_keyword_bag_of_words() -> None:
    embedder = FakeEmbedder()
    vectors = await embedder.embed(["Restart postgres now", "jellyfin"])
    assert vectors[0][0] == 1.0  # postgres
    assert vectors[0][9] == 1.0  # restart
    assert vectors[1][8] == 1.0  # jellyfin
    assert vectors[1][0] == 0.0
