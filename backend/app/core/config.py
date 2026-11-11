"""Configuración del backend (variables de entorno / archivo .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Modelo por defecto según la clave disponible. Se puede forzar con LLM_MODEL (sintaxis LiteLLM).
DEFAULT_CLOUD_MODELS: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_API_KEY", "anthropic/claude-sonnet-5-5"),
    ("GEMINI_API_KEY", "gemini/gemini-2.5-pro"),
    ("OPENAI_API_KEY", "openai/gpt-4.1"),
)
PROVIDER_KEY_BY_PREFIX = {
    "anthropic/": "ANTHROPIC_API_KEY",
    "gemini/": "GEMINI_API_KEY",
    "openai/": "OPENAI_API_KEY",
}


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv es opcional: las variables de entorno siguen funcionando
        return
    load_dotenv(BACKEND_DIR / ".env", override=False)


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

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        keys = {
            name: os.environ[name].strip()
            for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")
            if os.environ.get(name, "").strip()
        }
        return cls(
            database_url=os.environ.get("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'catalejo.db').as_posix()}"),
            storage_dir=Path(os.environ.get("STORAGE_DIR", str(BACKEND_DIR / "storage"))),
            llm_model=os.environ.get("LLM_MODEL", "").strip() or None,
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "ollama/llama3.1:8b"),
            llm_timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "600")),
            api_keys=keys,
            ollama_num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "32768")),
            # Los modelos locales son mucho más lentos: con 600 s el memo de qwen3:8b expiraba en CPU/GPU modesta.
            ollama_timeout_s=float(os.environ.get("OLLAMA_TIMEOUT_S", "1800")),
        )

    def cloud_model(self) -> Optional[str]:
        """Modelo cloud utilizable, o None si no hay clave para ningún proveedor."""
        if self.llm_model and not self.llm_model.startswith("ollama/"):
            required = next((k for p, k in PROVIDER_KEY_BY_PREFIX.items() if self.llm_model.startswith(p)), None)
            if required is None or required in self.api_keys:
                return self.llm_model
            return None
        for key_name, model in DEFAULT_CLOUD_MODELS:
            if key_name in self.api_keys:
                return model
        return None

    def deal_storage(self, deal_id: str) -> Path:
        """Carpeta exclusiva de la operación (aislamiento de archivos por deal_id)."""
        safe = "".join(ch for ch in deal_id if ch.isalnum() or ch in "-_")
        if not safe:
            raise ValueError("deal_id inválido")
        path = self.storage_dir / "deals" / safe
        path.mkdir(parents=True, exist_ok=True)
        return path
