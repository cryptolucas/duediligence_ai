"""Configuración del backend (variables de entorno / archivo .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProviderSpec:
    """Proveedor con API compatible con OpenAI (``/chat/completions``)."""

    label: str
    base_url: str
    key_env: str
    default_model: str
    # Tokens de entrada por llamada. Los planes gratuitos limitan los tokens por minuto (TPM): una llamada más
    # grande que el límite se rechaza, así que el contexto se trocea por debajo de este valor. Se ajusta solo
    # si el proveedor responde "request too large".
    max_input_tokens: int
    free: bool = True


# Proveedores gratuitos con modelos abiertos primero. El modelo se elige con LLM_MODEL usando el prefijo del
# proveedor (ej. groq/llama-3.3-70b-versatile); si no se define, se usa el primer proveedor con API key.
PROVIDERS: dict[str, ProviderSpec] = {
    "groq": ProviderSpec("Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile", 6000),
    "openrouter": ProviderSpec(
        "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "meta-llama/llama-3.3-70b-instruct:free", 12000
    ),
    "cerebras": ProviderSpec("Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gpt-oss-120b", 8000),
    "gemini": ProviderSpec(
        "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash", 30000
    ),
    "mistral": ProviderSpec("Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", 16000),
}
PROVIDER_ORDER: tuple[str, ...] = ("groq", "openrouter", "cerebras", "gemini", "mistral")
# Modelo de respaldo por proveedor (cuota independiente): si el principal agota su límite, se usa este.
DEFAULT_FALLBACKS: dict[str, tuple[str, ...]] = {"groq": ("groq/openai/gpt-oss-120b",)}
CUSTOM_PREFIX = "custom/"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv es opcional: las variables de entorno siguen funcionando
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


def normalize_database_url(url: str) -> str:
    """Neon / Render / Supabase entregan ``postgres://`` o ``postgresql://``; SQLAlchemy necesita el driver psycopg."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip().rstrip("/") for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_dir: Path
    llm_model: Optional[str]
    ollama_base_url: str
    ollama_model: str
    llm_timeout_s: float
    api_keys: dict[str, str] = field(default_factory=dict)
    ollama_num_ctx: int = 32768
    ollama_timeout_s: float = 1800.0
    llm_fallback_models: Optional[tuple[str, ...]] = None  # None = respaldo por defecto del proveedor
    llm_base_url: Optional[str] = None  # servidor propio compatible con OpenAI (vLLM, LM Studio...)
    llm_api_key: Optional[str] = None
    llm_max_input_tokens: Optional[int] = None
    llm_max_output_tokens: int = 3000
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    cors_origin_regex: Optional[str] = None
    access_code: Optional[str] = None
    max_concurrent_jobs: int = 2
    # Frontend exportado (next build con STATIC_EXPORT=1): si existe, el backend lo sirve en la misma URL que la API.
    frontend_dir: Optional[Path] = None

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        key_names = {spec.key_env for spec in PROVIDERS.values()}
        keys = {name: os.environ[name].strip() for name in sorted(key_names) if os.environ.get(name, "").strip()}
        fallbacks = os.environ.get("LLM_FALLBACK_MODELS")
        max_input = os.environ.get("LLM_MAX_INPUT_TOKENS", "").strip()
        cors = _csv(os.environ.get("CORS_ORIGINS", ""))
        return cls(
            database_url=normalize_database_url(
                os.environ.get("DATABASE_URL", "").strip() or f"sqlite:///{(BACKEND_DIR / 'catalejo.db').as_posix()}"
            ),
            storage_dir=Path(os.environ.get("STORAGE_DIR", str(BACKEND_DIR / "storage"))),
            llm_model=os.environ.get("LLM_MODEL", "").strip() or None,
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "ollama/llama3.1:8b"),
            llm_timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "180")),
            api_keys=keys,
            ollama_num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "32768")),
            # Los modelos locales son mucho más lentos: con 600 s el memo de qwen3:8b expiraba en CPU/GPU modesta.
            ollama_timeout_s=float(os.environ.get("OLLAMA_TIMEOUT_S", "1800")),
            llm_fallback_models=_csv(fallbacks) if fallbacks is not None else None,
            llm_base_url=os.environ.get("LLM_BASE_URL", "").strip().rstrip("/") or None,
            llm_api_key=os.environ.get("LLM_API_KEY", "").strip() or None,
            llm_max_input_tokens=int(max_input) if max_input else None,
            llm_max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "3000")),
            cors_origins=cors or ("http://localhost:3000", "http://127.0.0.1:3000"),
            cors_origin_regex=os.environ.get("CORS_ORIGIN_REGEX", "").strip() or None,
            access_code=os.environ.get("ACCESS_CODE", "").strip() or None,
            max_concurrent_jobs=max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "2"))),
            frontend_dir=Path(os.environ["FRONTEND_DIR"]) if os.environ.get("FRONTEND_DIR", "").strip() else None,
        )

    # ------------------------------------------------------------------ modelos cloud

    def provider_of(self, model: str) -> Optional[str]:
        if model.startswith(CUSTOM_PREFIX):
            return "custom"
        prefix = model.split("/", 1)[0]
        return prefix if prefix in PROVIDERS else None

    def _usable(self, model: str) -> bool:
        provider = self.provider_of(model)
        if provider == "custom":
            return self.llm_base_url is not None
        return provider is not None and PROVIDERS[provider].key_env in self.api_keys

    def cloud_model(self) -> Optional[str]:
        """Modelo principal utilizable (``proveedor/modelo``), o None si no hay API key de ningún proveedor."""
        if self.llm_model and not self.llm_model.startswith("ollama/"):
            model = self.llm_model
            if self.llm_base_url and self.provider_of(model) is None:
                model = CUSTOM_PREFIX + model  # LLM_BASE_URL + LLM_MODEL sin prefijo: servidor propio
            return model if self._usable(model) else None
        for name in PROVIDER_ORDER:
            spec = PROVIDERS[name]
            if spec.key_env in self.api_keys:
                return f"{name}/{spec.default_model}"
        return None

    def cloud_candidates(self) -> list[str]:
        """Modelo principal seguido de los de respaldo que tengan API key (sin duplicados)."""
        primary = self.cloud_model()
        if primary is None:
            return []
        if self.llm_fallback_models is not None:
            fallbacks = self.llm_fallback_models
        else:
            fallbacks = DEFAULT_FALLBACKS.get(self.provider_of(primary) or "", ())
        out = [primary]
        for model in fallbacks:
            if model not in out and self._usable(model):
                out.append(model)
        return out

    def deal_storage(self, deal_id: str) -> Path:
        """Carpeta exclusiva de la operación (aislamiento de archivos por deal_id)."""
        safe = "".join(ch for ch in deal_id if ch.isalnum() or ch in "-_")
        if not safe:
            raise ValueError("deal_id inválido")
        path = self.storage_dir / "deals" / safe
        path.mkdir(parents=True, exist_ok=True)
        return path
