"""Tests for the provider-agnostic LLM client (offline — httpx is stubbed)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.config import Settings
from app.llm_client import (
    DEFAULT_PROVIDER,
    PROVIDER_KEYS,
    PROVIDERS,
    LLMClient,
    LLMConfigError,
    LLMError,
    resolve_provider,
)


def _stub_transport(client: LLMClient, handler) -> list[httpx.Request]:
    """Route the client's httpx calls to `handler`, recording every request."""
    seen: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client._client = httpx.Client(transport=httpx.MockTransport(_handle))
    return seen


def _chat_reply(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


# ------------------------------------------------------------------- registry


def test_gemini_is_gone():
    assert "gemini" not in PROVIDER_KEYS
    assert "google" not in PROVIDER_KEYS


def test_popular_providers_are_registered():
    for key in ("openai", "anthropic", "ollama", "ollama_cloud", "groq", "openrouter"):
        assert key in PROVIDERS


def test_retired_provider_falls_back_instead_of_crashing():
    # An old `.env` saying LLM_PROVIDER=gemini must not break the app.
    assert resolve_provider("gemini").key == "openai_compatible"


def test_blank_provider_uses_the_default():
    assert resolve_provider("").key == DEFAULT_PROVIDER
    assert resolve_provider(None).key == DEFAULT_PROVIDER


def test_unknown_provider_is_rejected():
    with pytest.raises(LLMConfigError, match="Unknown LLM provider"):
        resolve_provider("hal9000")


def test_provider_name_is_case_insensitive():
    assert resolve_provider("  OpenAI ").key == "openai"


# ---------------------------------------------------------------------- ollama


def test_ollama_local_needs_no_api_key():
    client = LLMClient(provider="ollama")
    seen = _stub_transport(client, lambda _r: _chat_reply({"score": 1}))

    assert client("hi") == {"score": 1}
    request = seen[0]
    assert str(request.url) == "http://localhost:11434/v1/chat/completions"
    # No bogus `Authorization: Bearer ` header when there is no key.
    assert "authorization" not in request.headers


def test_ollama_cloud_sends_the_bearer_token():
    client = LLMClient(provider="ollama_cloud", api_key="secret")
    seen = _stub_transport(client, lambda _r: _chat_reply({"ok": True}))

    client("hi")
    assert str(seen[0].url) == "https://ollama.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer secret"


def test_ollama_cloud_without_a_key_fails_before_the_request():
    client = LLMClient(provider="ollama_cloud")
    seen = _stub_transport(client, lambda _r: _chat_reply({}))

    with pytest.raises(LLMConfigError, match="API key is required"):
        client("hi")
    assert seen == []


def test_local_provider_connection_error_is_actionable():
    client = LLMClient(provider="ollama")

    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _stub_transport(client, _refuse)
    with pytest.raises(LLMError, match="Is the local server running"):
        client("hi")


# ----------------------------------------------------------------- openai-style


def test_openai_sends_json_mode_and_bearer_auth():
    client = LLMClient(provider="openai", api_key="sk-test")
    seen = _stub_transport(client, lambda _r: _chat_reply({"score": 42}))

    assert client("prompt")["score"] == 42
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == PROVIDERS["openai"].default_model
    assert seen[0].headers["authorization"] == "Bearer sk-test"


def test_openai_compatible_requires_an_explicit_base_url():
    client = LLMClient(provider="openai_compatible", model="m")
    with pytest.raises(LLMConfigError, match="base URL is required"):
        client("hi")


def test_explicit_base_url_and_model_override_the_defaults():
    client = LLMClient(
        provider="groq", api_key="k", base_url="https://proxy.internal/v1/", model="my-model"
    )
    seen = _stub_transport(client, lambda _r: _chat_reply({"ok": True}))

    client("hi")
    assert str(seen[0].url) == "https://proxy.internal/v1/chat/completions"
    assert json.loads(seen[0].content)["model"] == "my-model"


def test_api_error_surfaces_the_provider_response():
    client = LLMClient(provider="openai", api_key="bad")
    _stub_transport(client, lambda _r: httpx.Response(401, text="invalid api key"))

    with pytest.raises(LLMError, match="401 invalid api key"):
        client("hi")


# -------------------------------------------------------------------- anthropic


def test_anthropic_uses_the_messages_api():
    client = LLMClient(provider="anthropic", api_key="sk-ant")
    seen = _stub_transport(
        client,
        lambda _r: httpx.Response(200, json={"content": [{"text": '{"score": 7}'}]}),
    )

    assert client("hi") == {"score": 7}
    request = seen[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant"
    assert request.headers["anthropic-version"] == "2023-06-01"
    # The Messages API rejects OpenAI's response_format.
    assert "response_format" not in json.loads(request.content)


# --------------------------------------------------------------------- parsing


def test_fenced_json_is_recovered():
    client = LLMClient(provider="ollama")
    _stub_transport(
        client,
        lambda _r: httpx.Response(
            200,
            json={"choices": [{"message": {"content": 'Sure!\n```json\n{"score": 3}\n```'}}]},
        ),
    )
    assert client("hi") == {"score": 3}


def test_non_json_output_fails_loudly():
    client = LLMClient(provider="ollama")
    _stub_transport(
        client, lambda _r: httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]})
    )
    with pytest.raises(LLMError, match="did not return valid JSON"):
        client("hi")


# -------------------------------------------------------------------- settings


def test_from_settings_maps_the_configured_provider():
    settings = Settings(
        llm_provider="deepseek", llm_api_key="k", llm_model="deepseek-reasoner", llm_base_url=""
    )
    client = LLMClient.from_settings(settings)
    assert client.provider == "deepseek"
    assert client.base_url == "https://api.deepseek.com/v1"
    assert client.model == "deepseek-reasoner"
