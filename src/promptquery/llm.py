from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from urllib import error as urlerror
from urllib import request


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    name: str

    @abstractmethod
    def generate(self, system: str, user: str) -> str: ...


class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("anthropic package not installed") from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model

    def generate(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=2000,
            # Determinism is a feature: the same question should yield the same SQL.
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)


class OpenAIClient(LLMClient):
    name = "openai"

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        try:
            import openai
        except ImportError as e:
            raise LLMError("openai package not installed (pip install promptquery[openai])") from e
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY is not set")
        self._client = openai.OpenAI(api_key=key)
        self.model = model

    # Reasoning-class OpenAI models (GPT-5.x, o1, o3, o4) accept
    # `max_completion_tokens` and reject the legacy `max_tokens` parameter.
    _REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

    def generate(self, system: str, user: str) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.model.startswith(self._REASONING_PREFIXES):
            # Reasoning models reject `temperature`/`seed`; they sample internally.
            kwargs["max_completion_tokens"] = 4000
        else:
            kwargs["max_tokens"] = 2000
            # Determinism is a feature: same question -> same SQL. temperature=0
            # plus a fixed seed gives best-effort reproducibility on chat models.
            kwargs["temperature"] = 0
            kwargs["seed"] = 0
        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(self, model: str = "llama3", base_url: str | None = None):
        self.model = model
        endpoint = base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
        self.base_url = endpoint.rstrip("/")

    def generate(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                body = response.read()
        except urlerror.URLError as e:
            raise LLMError(f"ollama request failed: {e}") from e

        try:
            data = json.loads(body.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise LLMError("ollama response missing choices[0].message.content") from e
        return content or ""


_SQL_BLOCK_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    match = _SQL_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip().rstrip(";").strip()
    return text.strip().rstrip(";").strip()


def make_client(model_spec: str | None = None) -> LLMClient:
    if model_spec:
        provider, _, model = model_spec.partition("/")
        if not model:
            # No explicit provider — guess from model name
            if provider.startswith("claude"):
                return AnthropicClient(model=provider)
            if provider.startswith(("gpt", "o1", "o3", "o4")):
                return OpenAIClient(model=provider)
            if provider == "ollama":
                return OllamaClient()
            raise LLMError(
                f"Cannot infer provider from model {provider!r}. "
                "Use 'anthropic/<model>', 'openai/<model>', or 'ollama/<model>'."
            )
        if provider == "anthropic":
            return AnthropicClient(model=model)
        if provider == "openai":
            return OpenAIClient(model=model)
        if provider == "ollama":
            return OllamaClient(model=model)
        raise LLMError(f"Unknown provider: {provider!r}")

    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIClient()
    raise LLMError(
        "No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )
