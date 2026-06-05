from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    name: str

    @abstractmethod
    def generate(self, system: str, user: str) -> str: ...


class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None,
                 temperature: float = 0):
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("anthropic package not installed") from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model
        self.temperature = temperature

    def generate(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=2000,
            temperature=self.temperature,
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

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None,
                 temperature: float = 0):
        try:
            import openai
        except ImportError as e:
            raise LLMError("openai package not installed (pip install promptquery[openai])") from e
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY is not set")
        self._client = openai.OpenAI(api_key=key)
        self.model = model
        self.temperature = temperature

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
            # self.temperature is intentionally not forwarded here.
            kwargs["max_completion_tokens"] = 4000
        else:
            kwargs["max_tokens"] = 2000
            kwargs["temperature"] = self.temperature
            kwargs["seed"] = 0
        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


_SQL_BLOCK_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    match = _SQL_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip().rstrip(";").strip()
    return text.strip().rstrip(";").strip()


def make_client(model_spec: str | None = None, temperature: float = 0) -> LLMClient:
    if model_spec:
        provider, _, model = model_spec.partition("/")
        if not model:
            # No explicit provider — guess from model name
            if provider.startswith("claude"):
                return AnthropicClient(model=provider, temperature=temperature)
            if provider.startswith("gpt") or provider.startswith("o1") or provider.startswith("o3"):
                return OpenAIClient(model=provider, temperature=temperature)
            raise LLMError(
                f"Cannot infer provider from model {provider!r}. "
                "Use 'anthropic/<model>' or 'openai/<model>'."
            )
        if provider == "anthropic":
            return AnthropicClient(model=model, temperature=temperature)
        if provider == "openai":
            return OpenAIClient(model=model, temperature=temperature)
        raise LLMError(f"Unknown provider: {provider!r}")

    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient(temperature=temperature)
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIClient(temperature=temperature)
    raise LLMError(
        "No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )
