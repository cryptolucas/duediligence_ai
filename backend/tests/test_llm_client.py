"""Cliente LLM (HTTP compatible con OpenAI y Ollama nativo): salida estructurada, reintentos y respaldo (sin red)."""

from __future__ import annotations

import pytest

from app.agents.llm_schemas import MemoResponse
from app.core.config import Settings
from app.services.llm_client import (
    Endpoint,
    HttpResult,
    LLMContextTooLarge,
    LLMError,
    OllamaClient,
    OpenAICompatibleClient,
    extract_json_object,
)


def ok(text: str, finish: str = "stop") -> HttpResult:
    return HttpResult(200, {}, {"choices": [{"message": {"content": text}, "finish_reason": finish}]})


def err(status: int, message: str, headers: dict | None = None) -> HttpResult:
    return HttpResult(status, headers or {}, {"error": {"message": message}})


class FakePost:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, url, headers, payload, timeout_s):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def client(replies, endpoints=None, **kwargs) -> tuple[OpenAICompatibleClient, FakePost, list]:
    post = FakePost(replies)
    sleeps: list[float] = []
    endpoints = endpoints or [Endpoint("groq/llama-3.3-70b-versatile", "Groq", "https://api.groq.com/openai/v1", "gsk-test", "llama-3.3-70b-versatile")]
    c = OpenAICompatibleClient(mode="CLOUD_API", endpoints=endpoints, post=post, sleep=sleeps.append, **kwargs)
    return c, post, sleeps


def test_extract_json_object_variants():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Aquí va: {"a": {"b": 2}} fin') == {"a": {"b": 2}}
    # Modelos con razonamiento (qwen3, deepseek) anteponen <think> con llaves que no son el JSON
    assert extract_json_object('<think>pienso {x} y {y}</think>\n{"a": 3}') == {"a": 3}
    with pytest.raises(ValueError):
        extract_json_object("sin json")


def test_complete_json_retries_once_with_correction_and_uses_json_mode():
    c, post, _ = client([ok("no es json"), ok('{"memo_markdown": "# Memo"}')])
    out = c.complete_json("sistema", "usuario", MemoResponse, deal_id="deal-abc", task="memo_writer")
    assert out.memo_markdown == "# Memo"
    assert c.calls == 2
    first = post.calls[0]
    assert first["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert first["headers"]["Authorization"] == "Bearer gsk-test"
    assert first["payload"]["temperature"] == 0 and first["payload"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in first["payload"]["messages"][0]["content"]
    assert "no cumple el esquema" in post.calls[1]["payload"]["messages"][-1]["content"]


def test_truncated_answer_asks_for_shorter_json():
    c, post, _ = client([ok('{"memo_markdown": "# Me', finish="length"), ok('{"memo_markdown": "corto"}')])
    assert c.complete_json("s", "u", MemoResponse, deal_id="d", task="t").memo_markdown == "corto"
    assert "se cortó por longitud" in post.calls[1]["payload"]["messages"][-1]["content"]


def test_rate_limit_waits_retry_after_then_succeeds():
    c, post, sleeps = client([err(429, "Rate limit reached", {"retry-after": "7"}), ok('{"memo_markdown": "ok"}')])
    assert c.complete_json("s", "u", MemoResponse, deal_id="d", task="t").memo_markdown == "ok"
    assert sleeps == [7.5]


def test_long_rate_limit_switches_to_fallback_model():
    endpoints = [
        Endpoint("groq/llama-3.3-70b-versatile", "Groq", "https://g", "k", "llama-3.3-70b-versatile"),
        Endpoint("groq/openai/gpt-oss-120b", "Groq", "https://g", "k", "openai/gpt-oss-120b"),
    ]
    c, post, sleeps = client(
        [err(429, "Rate limit reached on tokens per day (TPD). Please try again in 12m30s."), ok('{"memo_markdown": "respaldo"}')],
        endpoints=endpoints,
    )
    assert c.complete_json("s", "u", MemoResponse, deal_id="d", task="t").memo_markdown == "respaldo"
    assert sleeps == []  # no espera 12 minutos: pasa al respaldo
    assert c.model == "groq/openai/gpt-oss-120b"
    assert post.calls[1]["payload"]["model"] == "openai/gpt-oss-120b"
    assert post.calls[1]["payload"]["reasoning_effort"] == "low"
    # El modelo agotado queda bloqueado: la siguiente llamada va directo al respaldo
    post.replies.append(ok('{"memo_markdown": "otra"}'))
    c.complete_json("s", "u", MemoResponse, deal_id="d", task="t")
    assert post.calls[-1]["payload"]["model"] == "openai/gpt-oss-120b"


def test_request_too_large_shrinks_budget_and_raises():
    c, _, _ = client([err(413, "Request too large for model on tokens per minute (TPM): Limit 6000, Requested 9100")], max_input_tokens=8000)
    with pytest.raises(LLMContextTooLarge) as info:
        c.complete_json("s", "u", MemoResponse, deal_id="d", task="t")
    assert info.value.limit_tokens == 6000
    assert c.max_input_tokens < 6000 and c.max_input_tokens + c.max_output_tokens <= 6000


def test_invalid_key_and_network_errors_become_llm_error():
    c, _, _ = client([err(401, "Invalid API Key")])
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        c.complete_json("s", "u", MemoResponse, deal_id="d", task="t")
    c, _, sleeps = client([ConnectionError("sin red")] * 3)
    with pytest.raises(LLMError, match="sin conexión"):
        c.complete_json("s", "u", MemoResponse, deal_id="d", task="t")
    assert len(sleeps) == 2


def test_json_mode_unsupported_falls_back_to_prompt_only():
    c, post, _ = client([err(400, "response_format json_object is not supported by this model"), ok('{"memo_markdown": "ok"}')])
    assert c.complete_json("s", "u", MemoResponse, deal_id="d", task="t").memo_markdown == "ok"
    assert "response_format" not in post.calls[1]["payload"]


def test_ollama_client_uses_native_api_with_num_ctx():
    post = FakePost([HttpResult(200, {}, {"message": {"content": '{"memo_markdown": "local"}'}})])
    c = OllamaClient(mode="LOCAL_OLLAMA", model="ollama/qwen3:8b", base_url="http://localhost:11434", num_ctx=32768, post=post)
    assert c.complete_json("s", "u", MemoResponse, deal_id="d", task="t").memo_markdown == "local"
    call = post.calls[0]
    assert call["url"] == "http://localhost:11434/api/chat"
    assert call["payload"]["model"] == "qwen3:8b" and call["payload"]["options"]["num_ctx"] == 32768
    assert call["payload"]["format"] == "json" and call["payload"]["stream"] is False


def test_pick_ollama_model_prefers_configured_then_installed():
    from app.services.llm_client import pick_ollama_model

    assert pick_ollama_model("ollama/qwen3:8b", ["qwen3:8b"]) == ("ollama/qwen3:8b", "")
    assert pick_ollama_model("ollama/mistral", ["mistral:latest"])[0] == "ollama/mistral"
    model, note = pick_ollama_model("ollama/llama3.1:8b", ["qwen3:8b"])
    assert model == "ollama/qwen3:8b" and "no está descargado" in note
    assert pick_ollama_model("ollama/llama3.1:8b", [])[0] is None


def test_resolve_llm_local_uses_installed_model_and_large_context(monkeypatch, settings):
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "ollama_models", lambda base, timeout_s=1.5: ["qwen3:8b"])
    resolution = llm_client.resolve_llm("LOCAL_OLLAMA", settings)
    assert resolution.effective_mode == "LOCAL_OLLAMA"
    assert resolution.client.model == "ollama/qwen3:8b"
    assert resolution.client.num_ctx == 32768
    monkeypatch.setattr(llm_client, "ollama_models", lambda base, timeout_s=1.5: [])
    assert llm_client.resolve_llm("LOCAL_OLLAMA", settings).effective_mode == "RULES_FALLBACK"


def _settings(settings: Settings, **changes) -> Settings:
    return settings.__class__(**{**settings.__dict__, **changes})


def test_free_provider_selection_and_fallbacks(settings):
    from app.services.llm_client import resolve_llm

    assert _settings(settings).cloud_model() is None
    groq = _settings(settings, api_keys={"GROQ_API_KEY": "gsk"})
    assert groq.cloud_candidates() == ["groq/llama-3.3-70b-versatile", "groq/openai/gpt-oss-120b"]
    resolution = resolve_llm("CLOUD_API", groq)
    assert resolution.effective_mode == "CLOUD_API" and "Groq" in resolution.reason
    assert resolution.client.max_input_tokens == 6000
    # Modelo explícito sin su API key -> no disponible
    assert _settings(settings, llm_model="openrouter/x:free", api_keys={"GROQ_API_KEY": "gsk"}).cloud_model() is None
    # Respaldo de otro proveedor solo si hay clave
    mixed = _settings(
        settings,
        api_keys={"GROQ_API_KEY": "g", "GEMINI_API_KEY": "m"},
        llm_fallback_models=("gemini/gemini-2.5-flash", "openrouter/y:free"),
    )
    assert mixed.cloud_candidates() == ["groq/llama-3.3-70b-versatile", "gemini/gemini-2.5-flash"]
    # Servidor propio compatible con OpenAI
    custom = _settings(settings, llm_model="qwen2.5-32b", llm_base_url="http://mi-servidor:8000/v1")
    assert custom.cloud_model() == "custom/qwen2.5-32b"


def test_database_url_normalization():
    from app.core.config import normalize_database_url

    assert normalize_database_url("postgres://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_database_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"
