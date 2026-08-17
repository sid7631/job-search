"""Provider-agnostic LLM client.

One registry (`PROVIDERS`) describes every supported provider: its endpoint style,
default base URL and model, and whether it needs an API key. Everything else in the
app (settings API, frontend dropdown, docs) is driven from that registry, so adding
a provider means adding one entry here.

Two endpoint styles cover every provider:
- `chat`      -> OpenAI-style POST {base_url}/chat/completions
- `anthropic` -> Claude Messages API POST {base_url}/messages

Uses only `httpx` (already a dependency). No provider SDKs required.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

ApiStyle = Literal["chat", "anthropic"]


@dataclass(frozen=True)
class ProviderSpec:
    """Everything the client needs to talk to one provider."""

    key: str
    label: str
    api: ApiStyle
    base_url: str
    default_model: str
    # False for local runtimes (Ollama, LM Studio) and self-hosted gateways that
    # may or may not sit behind auth — the key header is sent only when set.
    requires_key: bool = True
    # Whether the endpoint accepts OpenAI's `response_format={"type":"json_object"}`.
    supports_json_mode: bool = True
    docs_url: str = ""


PROVIDER_LIST: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        key="openai",
        label="OpenAI",
        api="chat",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        docs_url="https://platform.openai.com/api-keys",
    ),
    ProviderSpec(
        key="anthropic",
        label="Anthropic (Claude)",
        api="anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-5",
        # The Messages API has no response_format; JSON is requested in the prompt.
        supports_json_mode=False,
        docs_url="https://console.anthropic.com/settings/keys",
    ),
    ProviderSpec(
        key="ollama",
        label="Ollama (local)",
        api="chat",
        base_url="http://localhost:11434/v1",
        default_model="llama3.2",
        requires_key=False,
        docs_url="https://ollama.com/download",
    ),
    ProviderSpec(
        key="ollama_cloud",
        label="Ollama Cloud",
        api="chat",
        base_url="https://ollama.com/v1",
        default_model="gpt-oss:120b",
        docs_url="https://ollama.com/settings/keys",
    ),
    ProviderSpec(
        key="groq",
        label="Groq",
        api="chat",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        docs_url="https://console.groq.com/keys",
    ),
    ProviderSpec(
        key="deepseek",
        label="DeepSeek",
        api="chat",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        docs_url="https://platform.deepseek.com/api_keys",
    ),
    ProviderSpec(
        key="mistral",
        label="Mistral",
        api="chat",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
        docs_url="https://console.mistral.ai/api-keys",
    ),
    ProviderSpec(
        key="openrouter",
        label="OpenRouter",
        api="chat",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        docs_url="https://openrouter.ai/keys",
    ),
    ProviderSpec(
        key="together",
        label="Together AI",
        api="chat",
        base_url="https://api.together.xyz/v1",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        docs_url="https://api.together.ai/settings/api-keys",
    ),
    ProviderSpec(
        key="xai",
        label="xAI (Grok)",
        api="chat",
        base_url="https://api.x.ai/v1",
        default_model="grok-4",
        docs_url="https://console.x.ai",
    ),
    ProviderSpec(
        key="lmstudio",
        label="LM Studio (local)",
        api="chat",
        base_url="http://localhost:1234/v1",
        default_model="",
        requires_key=False,
        docs_url="https://lmstudio.ai",
    ),
    ProviderSpec(
        key="openai_compatible",
        label="Other (OpenAI-compatible)",
        api="chat",
        # No default: the user must supply the endpoint.
        base_url="",
        default_model="",
        requires_key=False,
    ),
)

PROVIDERS: dict[str, ProviderSpec] = {spec.key: spec for spec in PROVIDER_LIST}
PROVIDER_KEYS: tuple[str, ...] = tuple(PROVIDERS)
DEFAULT_PROVIDER = "ollama"

# Providers that were removed; mapped onto a still-supported equivalent so an old
# `.env` or DB override does not hard-fail on startup.
RETIRED_PROVIDERS: dict[str, str] = {
    "gemini": "openai_compatible",
    "google": "openai_compatible",
}


class LLMError(RuntimeError):
    """Raised when an LLM call fails or returns unusable output."""


class LLMConfigError(LLMError):
    """Raised when provider configuration is missing or invalid."""


def resolve_provider(name: str | None) -> ProviderSpec:
    """Look up a provider spec by key, tolerating blanks, case and retired names."""
    key = (name or "").strip().lower()
    if not key:
        return PROVIDERS[DEFAULT_PROVIDER]
    if key in RETIRED_PROVIDERS:
        replacement = RETIRED_PROVIDERS[key]
        logger.warning(
            "LLM provider '%s' is no longer supported; falling back to '%s'. "
            "Set LLM_PROVIDER (or the Settings page) to one of: %s",
            key,
            replacement,
            ", ".join(PROVIDER_KEYS),
        )
        return PROVIDERS[replacement]
    spec = PROVIDERS.get(key)
    if spec is None:
        raise LLMConfigError(
            f"Unknown LLM provider '{key}'. Choose one of: {', '.join(PROVIDER_KEYS)}."
        )
    return spec


class LLMClient:
    """Dependency-free LLM client that routes to the configured provider."""

    def __init__(
        self,
        provider: str,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout: float = 120.0,
    ):
        self.spec = resolve_provider(provider)
        self.provider = self.spec.key
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or self.spec.base_url).rstrip("/")
        self.model = (model or self.spec.default_model).strip()
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings, *, timeout: float = 120.0) -> LLMClient:
        """Build a client from effective settings (`.env` + DB overrides)."""
        return cls(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key or "",
            base_url=settings.llm_base_url or "",
            model=settings.llm_model or "",
            timeout=timeout,
        )

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __call__(self, prompt: str) -> dict[str, Any]:
        """Send a prompt and return the parsed JSON object."""
        self._validate()
        if self.spec.api == "anthropic":
            return self._request(*self._anthropic_request(prompt), self._anthropic_text)
        return self._request(*self._chat_request(prompt), self._chat_text)

    # ------------------------------------------------------------------ config

    def _validate(self) -> None:
        """Fail fast with an actionable message before spending a request."""
        if self.spec.requires_key and not self.api_key:
            raise LLMConfigError(
                f"An API key is required for provider '{self.provider}'. "
                f"Set LLM_API_KEY in .env or the API key field on the Settings page."
            )
        if not self.base_url:
            raise LLMConfigError(
                f"A base URL is required for provider '{self.provider}'. "
                f"Set LLM_BASE_URL in .env or the Base URL field on the Settings page."
            )
        if not self.model:
            raise LLMConfigError(
                f"A model name is required for provider '{self.provider}'. "
                f"Set LLM_MODEL in .env or the Model field on the Settings page."
            )

    # ----------------------------------------------------------- request build

    def _chat_request(self, prompt: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Build an OpenAI-style /chat/completions request."""
        headers = {"Content-Type": "application/json"}
        # Local runtimes usually have no auth; only send the header when a key exists.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if self.spec.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        return f"{self.base_url}/chat/completions", headers, payload

    def _anthropic_request(self, prompt: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Build an Anthropic Messages API request."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        return f"{self.base_url}/messages", headers, payload

    @staticmethod
    def _chat_text(data: dict[str, Any]) -> str:
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _anthropic_text(data: dict[str, Any]) -> str:
        return data["content"][0]["text"]

    # ---------------------------------------------------------------- transport

    def _status_hint(self, status: int) -> str:
        """Turn the common HTTP failures into the next thing to actually try."""
        if status in (401, 403):
            return (
                f" — the API key was rejected. Check it is a key for {self.spec.label} "
                f"(each provider issues its own), that it saved correctly, and that it "
                f"has not expired."
            )
        if status == 404:
            return (
                f" — endpoint or model not found. Check the model name "
                f"('{self.model}') exists on {self.spec.label}; many providers "
                f"require an exact tag, e.g. 'deepseek-v4-flash:0731'."
            )
        return ""

    def _request(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        extract_text: Callable[[dict[str, Any]], str],
    ) -> dict[str, Any]:
        """POST with 429 back-off, then pull a JSON object out of the reply."""
        last_exc: Exception | None = None
        for attempt in range(6):
            try:
                response = self._client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return _extract_json(extract_text(response.json()))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < 5:
                    wait = 8 * (attempt + 1)
                    logger.warning(
                        "%s rate-limited (attempt %d); waiting %ds",
                        self.provider,
                        attempt + 1,
                        wait,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
                status = exc.response.status_code
                raise LLMError(
                    f"{self.provider} API error: {status} {exc.response.text}"
                    f"{self._status_hint(status)}"
                ) from exc
            except httpx.ConnectError as exc:
                hint = (
                    " Is the local server running?"
                    if not self.spec.requires_key and "localhost" in self.base_url
                    else ""
                )
                raise LLMError(
                    f"{self.provider} unreachable at {self.base_url}: {exc}{hint}"
                ) from exc
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                raise LLMError(f"{self.provider} returned malformed JSON: {exc}") from exc
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(f"{self.provider} call failed: {exc}") from exc
        raise LLMError(f"{self.provider} rate limit did not clear: {last_exc}")

    def close(self) -> None:
        self._client.close()


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in a string (handles markdown fences)."""
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown code fences.
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Try to find the first `{` ... `}` block.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise LLMError(f"LLM did not return valid JSON: {exc}") from exc


def check_llm(settings: Settings, *, timeout: float = 30.0) -> str:
    """Send a trivial prompt to verify the provider is reachable and configured.

    Returns the model that answered. Raises `LLMError` / `LLMConfigError` otherwise.
    """
    with LLMClient.from_settings(settings, timeout=timeout) as client:
        client('Reply with exactly this JSON and nothing else: {"ok": true}')
        return client.model


def get_default_llm(settings: Settings | None = None) -> Callable[[str], dict[str, Any]]:
    """Return a callable that sends a prompt to the configured provider.

    The returned callable wraps a pooled `httpx.Client`, which is thread-safe, so it
    can be shared across the ranking thread pool.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    return LLMClient.from_settings(settings)
