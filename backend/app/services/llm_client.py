"""Capa LLM con salidas estructuradas Pydantic y selección de modo por operación.

* CLOUD_API: proveedor gratuito con modelos abiertos y API compatible con OpenAI (Groq por defecto; también
  OpenRouter, Cerebras, Gemini, Mistral o un servidor propio vía LLM_BASE_URL). Incluye modelo de respaldo.
* LOCAL_OLLAMA: modelo local vía Ollama para documentos confidenciales. Si Ollama no responde, NUNCA se cae
  a la nube: el deal se procesa en RULES_FALLBACK (reglas deterministas).
* Sin claves: RULES_FALLBACK.

Se habla HTTP directo con ``httpx`` (sin LiteLLM): menos memoria y una instalación de segundos, clave en los
planes gratuitos de hosting. Los planes gratuitos limitan tokens por minuto (TPM), así que el cliente:
- reintenta los 429 respetando ``retry-after`` y pasa al modelo de respaldo si la espera es larga;
- ante "request too large" reduce ``max_input_tokens`` y lanza ``LLMContextTooLarge`` para que el agente
  divida el contexto en partes más pequeñas (ver ``app.agents.context.run_chunked``).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import CUSTOM_PREFIX, PROVIDERS, Settings

T = TypeVar("T", bound=BaseModel)

THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
TOO_LARGE_RE = re.compile(
    r"request too large|context[_ ]length|maximum context|too many tokens|reduce the length|prompt is too long|input is too long",
    re.IGNORECASE,
)
LIMIT_RE = re.compile(r"Limit\s+(\d+),\s*Requested\s+(\d+)", re.IGNORECASE)
TRY_AGAIN_RE = re.compile(r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?([\d.]+)?(ms|s)?", re.IGNORECASE)
MODEL_GONE_RE = re.compile(r"model.*(not found|does not exist|decommissioned|not supported|no longer)", re.IGNORECASE)


class LLMError(RuntimeError):
    """Fallo irrecuperable del LLM (red, cuota, clave inválida, salida inválida tras reintento)."""


class LLMContextTooLarge(LLMError):
    """La llamada supera el tamaño que admite el proveedor/plan. El agente debe dividir el contexto."""

    def __init__(self, message: str, limit_tokens: Optional[int] = None):
        super().__init__(message)
        self.limit_tokens = limit_tokens


class StructuredLLM(Protocol):
    mode: str
    model: str
    calls: int

    def complete_json(self, system: str, user: str, schema: type[T], *, deal_id: str, task: str) -> T: ...


def extract_json_object(text: str) -> dict:
    """Extrae el primer objeto JSON de una respuesta (tolera <think>, bloques ```json y texto alrededor)."""
    text = THINK_RE.sub("", text or "")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("La respuesta no contiene un objeto JSON.")
        candidate = text[start : end + 1]
    return json.loads(candidate)


def schema_instructions(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return (
        "Responde ÚNICAMENTE con un objeto JSON válido (json) que cumpla este JSON Schema, sin texto adicional "
        f"y con textos breves:\n{schema_json}"
    )


class _Truncated(str):
    """Respuesta cortada por longitud (finish_reason=length)."""


class _JsonClient:
    """Lógica común: instrucciones de esquema, validación Pydantic y un reintento con corrección."""

    calls: int
    max_input_tokens: int

    def _call(self, messages: list[dict], deal_id: str, task: str) -> str:  # pragma: no cover - abstracto
        raise NotImplementedError

    def complete_json(self, system: str, user: str, schema: type[T], *, deal_id: str, task: str) -> T:
        messages = [{"role": "system", "content": f"{system}\n\n{schema_instructions(schema)}"}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        for _ in range(2):
            raw = self._call(messages, deal_id, task)
            try:
                return schema.model_validate(extract_json_object(raw))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                hint = (
                    "Tu respuesta se cortó por longitud. Devuelve un JSON más corto (menos ítems y textos breves)."
                    if isinstance(raw, _Truncated)
                    else f"Tu respuesta no cumple el esquema: {str(exc)[:1200]}. Devuelve solo el JSON corregido."
                )
                messages = messages[:2] + [{"role": "assistant", "content": THINK_RE.sub("", raw)[:3000]}, {"role": "user", "content": hint}]
        raise LLMError(f"{task}: el modelo no devolvió un JSON válido tras reintentar ({str(last_error)[:300]}).")


# ---------------------------------------------------------------------------
# Proveedores compatibles con OpenAI (Groq, OpenRouter, Cerebras, Gemini, Mistral, servidor propio)
# ---------------------------------------------------------------------------


@dataclass
class Endpoint:
    spec: str  # "groq/llama-3.3-70b-versatile"
    label: str  # "Groq"
    base_url: str
    api_key: Optional[str]
    model_id: str  # "llama-3.3-70b-versatile"
    blocked_until: float = 0.0  # cuota agotada: no se usa hasta este instante (time.monotonic)


@dataclass
class HttpResult:
    status: int
    headers: dict
    body: object  # dict si la respuesta es JSON; texto si no


def _http_post(url: str, headers: dict, payload: dict, timeout_s: float) -> HttpResult:
    import httpx

    response = httpx.post(url, headers=headers, json=payload, timeout=timeout_s)
    try:
        body: object = response.json()
    except ValueError:
        body = response.text
    return HttpResult(response.status_code, {k.lower(): v for k, v in response.headers.items()}, body)


def _error_text(body: object) -> str:
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)
        return str(err)
    return str(body)[:500]


def _retry_after_s(result: HttpResult, message: str) -> Optional[float]:
    value = result.headers.get("retry-after")
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    match = TRY_AGAIN_RE.search(message)
    if match and any(match.groups()[:3]):
        hours, minutes, amount, unit = match.groups()
        seconds = float(amount or 0) / (1000 if unit == "ms" else 1)
        return int(hours or 0) * 3600 + int(minutes or 0) * 60 + seconds
    return None


@dataclass
class OpenAICompatibleClient(_JsonClient):
    mode: str
    endpoints: list[Endpoint]
    timeout_s: float = 180.0
    max_input_tokens: int = 6000
    max_output_tokens: int = 3000
    max_rate_limit_wait_s: float = 75.0  # espera máxima acumulada por llamada antes de pasar al respaldo
    calls: int = 0
    json_mode: bool = True
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    post: Callable[..., HttpResult] = field(default=_http_post, repr=False)
    active: int = 0

    @property
    def model(self) -> str:
        return self.endpoints[self.active].spec

    def _payload(self, endpoint: Endpoint, messages: list[dict]) -> dict:
        payload: dict = {
            "model": endpoint.model_id,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if "gpt-oss" in endpoint.model_id:
            payload["reasoning_effort"] = "low"  # el razonamiento consume tokens de salida y de cuota
        return payload

    def _shrink(self, limit: Optional[int]) -> None:
        if limit:
            self.max_output_tokens = min(self.max_output_tokens, max(800, int(limit * 0.4)))
            self.max_input_tokens = max(1200, int((limit - self.max_output_tokens) * 0.85))
        else:
            self.max_input_tokens = max(1200, int(self.max_input_tokens * 0.6))

    def _call(self, messages: list[dict], deal_id: str, task: str) -> str:
        errors: list[str] = []
        for index, endpoint in enumerate(self.endpoints):
            if endpoint.blocked_until > time.monotonic():
                errors.append(f"{endpoint.spec}: cuota agotada")
                continue
            try:
                text = self._call_endpoint(endpoint, messages, task)
            except LLMContextTooLarge:
                raise
            except _SkipEndpoint as exc:
                errors.append(f"{endpoint.spec}: {exc}")
                continue
            self.active = index
            return text
        raise LLMError(f"{task}: ningún modelo respondió. " + " | ".join(errors))

    def _call_endpoint(self, endpoint: Endpoint, messages: list[dict], task: str) -> str:
        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"
        if endpoint.spec.startswith("openrouter/"):
            headers["X-Title"] = "Catalejo Deal Desk"
        waited = 0.0
        transient_failures = 0
        while True:
            try:
                result = self.post(f"{endpoint.base_url}/chat/completions", headers, self._payload(endpoint, messages), self.timeout_s)
            except Exception as exc:  # noqa: BLE001 - red caída, DNS, timeout
                self.calls += 1
                transient_failures += 1
                if transient_failures > 2:
                    raise _SkipEndpoint(f"sin conexión ({type(exc).__name__})") from exc
                self.sleep(3 * transient_failures)
                continue
            self.calls += 1
            if result.status == 200 and isinstance(result.body, dict):
                choice = (result.body.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                return _Truncated(content) if choice.get("finish_reason") == "length" else content

            message = _error_text(result.body)
            limit = LIMIT_RE.search(message)
            too_large = result.status == 413 or bool(TOO_LARGE_RE.search(message)) or (
                limit is not None and int(limit.group(2)) > int(limit.group(1))
            )
            if too_large and result.status in (400, 413, 422, 429):
                self._shrink(int(limit.group(1)) if limit else None)
                raise LLMContextTooLarge(f"{task}: la solicitud supera el límite del modelo ({message[:200]}).", int(limit.group(1)) if limit else None)
            if result.status == 400 and "json_validate_failed" in message:
                failed = (result.body.get("error") or {}).get("failed_generation", "") if isinstance(result.body, dict) else ""
                return failed or ""  # se corrige con el reintento de complete_json
            if result.status == 400 and self.json_mode and re.search(r"response_format|json mode|json_object", message, re.IGNORECASE):
                self.json_mode = False  # el modelo no soporta modo JSON: se pide por prompt
                continue
            if result.status in (401, 403):
                raise _SkipEndpoint(f"API key inválida o sin permisos ({result.status}). Revise {_key_hint(endpoint)}.")
            if result.status == 404 or (result.status == 400 and MODEL_GONE_RE.search(message)):
                raise _SkipEndpoint(f"el modelo {endpoint.model_id} no está disponible ({message[:160]})")
            if result.status == 429:
                wait = _retry_after_s(result, message)
                if wait is None:
                    wait = min(60.0, 5.0 * (2 ** min(transient_failures, 3)))
                if waited + wait > self.max_rate_limit_wait_s:
                    endpoint.blocked_until = time.monotonic() + min(wait, 3600)
                    raise _SkipEndpoint(
                        f"límite del plan gratuito alcanzado; disponible de nuevo en ~{max(1, round(wait / 60))} min"
                    )
                transient_failures += 1
                waited += wait + 0.5
                self.sleep(wait + 0.5)
                continue
            if result.status >= 500:
                transient_failures += 1
                if transient_failures > 2:
                    raise _SkipEndpoint(f"el proveedor falló ({result.status})")
                self.sleep(4 * transient_failures)
                continue
            raise _SkipEndpoint(f"error {result.status}: {message[:200]}")


class _SkipEndpoint(Exception):
    """Este modelo no puede atender la llamada; se intenta con el siguiente (respaldo)."""


def _key_hint(endpoint: Endpoint) -> str:
    provider = endpoint.spec.split("/", 1)[0]
    return PROVIDERS[provider].key_env if provider in PROVIDERS else "LLM_API_KEY"


def build_endpoint(model: str, settings: Settings) -> Endpoint:
    if model.startswith(CUSTOM_PREFIX):
        return Endpoint(model, "Servidor propio", settings.llm_base_url or "", settings.llm_api_key, model[len(CUSTOM_PREFIX) :])
    provider, model_id = model.split("/", 1)
    spec = PROVIDERS[provider]
    return Endpoint(model, spec.label, spec.base_url, settings.api_keys.get(spec.key_env), model_id)


def describe_model(model: str) -> str:
    """Etiqueta legible: 'Groq · llama-3.3-70b-versatile'."""
    if model.startswith(CUSTOM_PREFIX):
        return f"Servidor propio · {model[len(CUSTOM_PREFIX):]}"
    provider, _, model_id = model.partition("/")
    label = PROVIDERS[provider].label if provider in PROVIDERS else provider
    return f"{label} · {model_id}"


# ---------------------------------------------------------------------------
# Ollama local (API nativa: permite fijar num_ctx)
# ---------------------------------------------------------------------------


@dataclass
class OllamaClient(_JsonClient):
    mode: str
    model: str  # "ollama/qwen3:8b"
    base_url: str
    timeout_s: float = 1800.0
    num_ctx: int = 32768
    calls: int = 0
    post: Callable[..., HttpResult] = field(default=_http_post, repr=False)

    @property
    def max_input_tokens(self) -> int:
        return int(self.num_ctx * 0.6)

    def _call(self, messages: list[dict], deal_id: str, task: str) -> str:
        payload = {
            "model": self.model.split("/", 1)[1],
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        try:
            result = self.post(f"{self.base_url}/api/chat", {"Content-Type": "application/json"}, payload, self.timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{task}: Ollama no respondió ({type(exc).__name__}: {exc})") from exc
        finally:
            self.calls += 1
        if result.status != 200 or not isinstance(result.body, dict):
            raise LLMError(f"{task}: Ollama devolvió {result.status} ({_error_text(result.body)[:200]})")
        return (result.body.get("message") or {}).get("content") or ""


# ---------------------------------------------------------------------------
# Resolución del modo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResolution:
    effective_mode: str  # CLOUD_API | LOCAL_OLLAMA | RULES_FALLBACK
    client: Optional[StructuredLLM]
    reason: str


def ollama_models(base_url: str, timeout_s: float = 1.5) -> Optional[list[str]]:
    """Modelos instalados en Ollama, o None si Ollama no responde."""
    try:
        import httpx

        response = httpx.get(f"{base_url}/api/tags", timeout=timeout_s)
        if response.status_code != 200:
            return None
        return [m.get("name", "") for m in response.json().get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001 - cualquier fallo de red = no disponible
        return None


def ollama_is_available(base_url: str, timeout_s: float = 1.5) -> bool:
    return ollama_models(base_url, timeout_s) is not None


def pick_ollama_model(configured: str, installed: list[str]) -> tuple[Optional[str], str]:
    """Usa el modelo configurado si está instalado; si no, el primero instalado. Devuelve (``ollama/<modelo>``, nota)."""
    wanted = configured.removeprefix("ollama/").removeprefix("ollama_chat/")
    candidates = {wanted, wanted if ":" in wanted else f"{wanted}:latest"}
    if any(name in candidates for name in installed):
        return f"ollama/{wanted}", ""
    if installed:
        return f"ollama/{installed[0]}", f" El modelo configurado ({wanted}) no está descargado; se usa {installed[0]}."
    return None, f" Ollama no tiene modelos descargados (ejecute: ollama pull {wanted})."


def cloud_client(settings: Settings) -> Optional[OpenAICompatibleClient]:
    candidates = settings.cloud_candidates()
    if not candidates:
        return None
    endpoints = [build_endpoint(m, settings) for m in candidates]
    provider = settings.provider_of(candidates[0])
    default_tokens = PROVIDERS[provider].max_input_tokens if provider in PROVIDERS else 8000
    return OpenAICompatibleClient(
        mode="CLOUD_API",
        endpoints=endpoints,
        timeout_s=settings.llm_timeout_s,
        max_input_tokens=settings.llm_max_input_tokens or default_tokens,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def resolve_llm(requested_mode: str, settings: Settings) -> LLMResolution:
    """Decide qué LLM usa una operación. Cada deal recibe su propio cliente (aislamiento)."""
    if requested_mode == "LOCAL_OLLAMA":
        installed = ollama_models(settings.ollama_base_url)
        model, note = pick_ollama_model(settings.ollama_model, installed) if installed is not None else (None, "")
        if model is not None:
            client = OllamaClient(
                mode="LOCAL_OLLAMA",
                model=model,
                base_url=settings.ollama_base_url,
                timeout_s=settings.ollama_timeout_s,
                # Ollama usa por defecto una ventana de contexto corta: se amplía para notas y balances completos.
                num_ctx=settings.ollama_num_ctx,
            )
            return LLMResolution("LOCAL_OLLAMA", client, f"Ollama local ({model.split('/', 1)[1]}).{note}")
        if installed is not None:
            return LLMResolution(
                "RULES_FALLBACK", None, f"Ollama responde pero no hay modelos.{note} Se procesa con reglas deterministas."
            )
        return LLMResolution(
            "RULES_FALLBACK",
            None,
            "Ollama no responde en "
            f"{settings.ollama_base_url}. Por confidencialidad no se usa la nube: se procesa con reglas deterministas.",
        )
    if requested_mode == "CLOUD_API":
        client = cloud_client(settings)
        if client is None:
            return LLMResolution(
                "RULES_FALLBACK",
                None,
                "El servidor no tiene configurada una API key de IA (ej. GROQ_API_KEY): se procesa con reglas deterministas.",
            )
        backup = [describe_model(e.spec) for e in client.endpoints[1:]]
        reason = f"Modelo de IA: {describe_model(client.model)}" + (f" (respaldo: {', '.join(backup)})." if backup else ".")
        return LLMResolution("CLOUD_API", client, reason)
    raise ValueError(f"Modo LLM no soportado: {requested_mode}")
