"""Capa LLM (LiteLLM) con salidas estructuradas Pydantic y selección de modo por operación.

* CLOUD_API: Anthropic / Gemini / OpenAI según la clave disponible (o LLM_MODEL).
* LOCAL_OLLAMA: modelo local vía Ollama para documentos confidenciales. Si Ollama no responde,
  NUNCA se cae a la nube: el deal se procesa en RULES_FALLBACK (reglas deterministas).
* Sin claves: RULES_FALLBACK.

LiteLLM se importa de forma diferida para que el motor determinista y los tests no lo carguen.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Fallo irrecuperable del LLM (red, cuota, salida inválida tras reintento)."""


class StructuredLLM(Protocol):
    mode: str
    model: str
    calls: int

    def complete_json(self, system: str, user: str, schema: type[T], *, deal_id: str, task: str) -> T: ...


def extract_json_object(text: str) -> dict:
    """Extrae el primer objeto JSON de una respuesta (tolera bloques ```json y texto alrededor)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("La respuesta no contiene un objeto JSON.")
        candidate = text[start : end + 1]
    return json.loads(candidate)


@dataclass
class LiteLLMClient:
    mode: str
    model: str
    api_base: Optional[str] = None
    timeout_s: float = 120.0
    extra_params: dict = field(default_factory=dict)
    calls: int = field(default=0)

    def _call(self, messages: list[dict], deal_id: str, task: str) -> str:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - dependencia instalada en requirements
            raise LLMError("LiteLLM no está instalado.") from exc
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "timeout": self.timeout_s,
            "drop_params": True,
            "response_format": {"type": "json_object"},
            "metadata": {"deal_id": deal_id, "task": task},
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        kwargs.update(self.extra_params)
        try:
            response = litellm.completion(**kwargs)
        except Exception as exc:  # noqa: BLE001 - LiteLLM envuelve errores de muchos proveedores
            raise LLMError(f"{task}: fallo del proveedor LLM ({type(exc).__name__}: {exc})") from exc
        finally:
            self.calls += 1
        return response.choices[0].message.content or ""

    def complete_json(self, system: str, user: str, schema: type[T], *, deal_id: str, task: str) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system_full = (
            f"{system}\n\nResponde ÚNICAMENTE con un objeto JSON válido que cumpla este JSON Schema "
            f"(sin texto adicional):\n{schema_json}"
        )
        messages = [{"role": "system", "content": system_full}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        for _ in range(2):
            raw = self._call(messages, deal_id, task)
            try:
                return schema.model_validate(extract_json_object(raw))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw[:4000]},
                    {
                        "role": "user",
                        "content": f"Tu respuesta no cumple el esquema: {str(exc)[:1500]}. Devuelve solo el JSON corregido.",
                    },
                ]
        raise LLMError(f"{task}: salida JSON inválida tras reintento ({last_error}).")


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
    """Usa el modelo configurado si está instalado; si no, el primero instalado. Devuelve (modelo LiteLLM, nota)."""
    wanted = configured.removeprefix("ollama/").removeprefix("ollama_chat/")
    candidates = {wanted, wanted if ":" in wanted else f"{wanted}:latest"}
    if any(name in candidates for name in installed):
        return f"ollama_chat/{wanted}", ""
    if installed:
        return f"ollama_chat/{installed[0]}", f" El modelo configurado ({wanted}) no está descargado; se usa {installed[0]}."
    return None, f" Ollama no tiene modelos descargados (ejecute: ollama pull {wanted})."


def resolve_llm(requested_mode: str, settings: Settings) -> LLMResolution:
    """Decide qué LLM usa una operación. Cada deal recibe su propio cliente (aislamiento)."""
    if requested_mode == "LOCAL_OLLAMA":
        installed = ollama_models(settings.ollama_base_url)
        model, note = pick_ollama_model(settings.ollama_model, installed) if installed is not None else (None, "")
        if model is not None:
            client = LiteLLMClient(
                mode="LOCAL_OLLAMA",
                model=model,
                api_base=settings.ollama_base_url,
                timeout_s=settings.ollama_timeout_s,
                # Ollama usa por defecto una ventana de contexto corta: se amplía para notas y balances completos.
                extra_params={"num_ctx": settings.ollama_num_ctx},
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
        model = settings.cloud_model()
        if model is None:
            return LLMResolution(
                "RULES_FALLBACK",
                None,
                "No hay OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY en .env: se procesa con reglas deterministas.",
            )
        return LLMResolution("CLOUD_API", LiteLLMClient("CLOUD_API", model, timeout_s=settings.llm_timeout_s), f"Modelo cloud {model}.")
    raise ValueError(f"Modo LLM no soportado: {requested_mode}")
