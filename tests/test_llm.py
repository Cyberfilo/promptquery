from __future__ import annotations

import json
from urllib import error as urlerror

import pytest

from promptquery.llm import LLMError, OllamaClient, make_client


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def test_ollama_client_posts_to_openai_compatible_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        seen["headers"] = dict(req.header_items())
        seen["payload"] = json.loads(req.data.decode("utf-8"))
        return _Response({
            "choices": [
                {"message": {"content": "```sql\nSELECT 1\n```"}},
            ],
        })

    monkeypatch.setattr("promptquery.llm.request.urlopen", fake_urlopen)

    client = OllamaClient(model="llama3.1", base_url="http://localhost:11434/")

    assert client.generate("system prompt", "user question") == "```sql\nSELECT 1\n```"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["timeout"] == 120
    assert seen["headers"]["Content-type"] == "application/json"
    assert seen["payload"] == {
        "model": "llama3.1",
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user question"},
        ],
        "temperature": 0,
    }


def test_ollama_client_uses_env_base_url(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return _Response({"choices": [{"message": {"content": "SELECT 1"}}]})

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test:11434/")
    monkeypatch.setattr("promptquery.llm.request.urlopen", fake_urlopen)

    assert OllamaClient().generate("system", "user") == "SELECT 1"
    assert seen["url"] == "http://ollama.test:11434/v1/chat/completions"


def test_ollama_client_wraps_http_errors(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urlerror.URLError("connection refused")

    monkeypatch.setattr("promptquery.llm.request.urlopen", fake_urlopen)

    with pytest.raises(LLMError, match="ollama request failed"):
        OllamaClient().generate("system", "user")


def test_ollama_client_rejects_malformed_response(monkeypatch):
    def fake_urlopen(req, timeout):
        return _Response({"choices": []})

    monkeypatch.setattr("promptquery.llm.request.urlopen", fake_urlopen)

    with pytest.raises(LLMError, match="choices"):
        OllamaClient().generate("system", "user")


def test_make_client_routes_ollama_models():
    client = make_client("ollama/llama3")

    assert isinstance(client, OllamaClient)
    assert client.model == "llama3"
