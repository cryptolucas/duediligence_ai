"""Cliente LiteLLM: salida estructurada, reintento ante JSON inválido y metadatos por deal (sin red)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.llm_schemas import MemoResponse
from app.services.llm_client import LiteLLMClient, LLMError, extract_json_object


def _response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_extract_json_object_variants():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Aquí va: {"a": {"b": 2}} fin') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json_object("sin json")


def test_complete_json_retries_once_and_passes_deal_metadata(monkeypatch):
    import litellm

    calls = []
    replies = iter(["no es json", '{"memo_markdown": "# Memo"}'])

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _response(next(replies))

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LiteLLMClient(mode="LOCAL_OLLAMA", model="ollama/llama3.1:8b", api_base="http://localhost:11434")
    out = client.complete_json("sistema", "usuario", MemoResponse, deal_id="deal-abc", task="memo_writer")
    assert out.memo_markdown == "# Memo"
    assert client.calls == 2
    first = calls[0]
    assert first["metadata"] == {"deal_id": "deal-abc", "task": "memo_writer"}
    assert first["temperature"] == 0 and first["api_base"] == "http://localhost:11434"
    assert "JSON Schema" in first["messages"][0]["content"]
    assert "no cumple el esquema" in calls[1]["messages"][-1]["content"]


def test_pick_ollama_model_prefers_configured_then_installed():
    from app.services.llm_client import pick_ollama_model

    assert pick_ollama_model("ollama/qwen3:8b", ["qwen3:8b"]) == ("ollama_chat/qwen3:8b", "")
    assert pick_ollama_model("ollama/mistral", ["mistral:latest"])[0] == "ollama_chat/mistral"
    model, note = pick_ollama_model("ollama/llama3.1:8b", ["qwen3:8b"])
    assert model == "ollama_chat/qwen3:8b" and "no está descargado" in note
    assert pick_ollama_model("ollama/llama3.1:8b", [])[0] is None


def test_resolve_llm_local_uses_installed_model_and_large_context(monkeypatch, settings):
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "ollama_models", lambda base, timeout_s=1.5: ["qwen3:8b"])
    resolution = llm_client.resolve_llm("LOCAL_OLLAMA", settings)
    assert resolution.effective_mode == "LOCAL_OLLAMA"
    assert resolution.client.model == "ollama_chat/qwen3:8b"
    assert resolution.client.extra_params == {"num_ctx": 32768}
    monkeypatch.setattr(llm_client, "ollama_models", lambda base, timeout_s=1.5: [])
    assert llm_client.resolve_llm("LOCAL_OLLAMA", settings).effective_mode == "RULES_FALLBACK"


def test_complete_json_raises_llm_error_on_provider_failure(monkeypatch):
    import litellm

    def boom(**kwargs):
        raise RuntimeError("sin red")

    monkeypatch.setattr(litellm, "completion", boom)
    client = LiteLLMClient(mode="CLOUD_API", model="openai/gpt-4.1")
    with pytest.raises(LLMError):
        client.complete_json("s", "u", MemoResponse, deal_id="d", task="t")
