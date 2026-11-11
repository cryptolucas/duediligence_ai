from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        storage_dir=tmp_path / "storage",
        llm_model=None,
        ollama_base_url="http://127.0.0.1:9",  # puerto cerrado: Ollama "no disponible"
        ollama_model="ollama/llama3.1:8b",
        llm_timeout_s=5,
        api_keys={},
    )


@pytest.fixture(scope="session")
def demo_files(tmp_path_factory) -> Path:
    """Exporta el caso demo como archivos reales (XLSX + PDF) una sola vez por sesión."""
    out = tmp_path_factory.mktemp("demo_files")
    spec = importlib.util.spec_from_file_location("export_demo_documents", BACKEND_DIR / "scripts" / "export_demo_documents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dossier = module.load_demo_dossier()
    for document in dossier.documents:
        target = out / document.document_name
        if document.file_format == "XLSX":
            module.export_xlsx(document, target)
        else:
            module.export_pdf(document, target)
    return out


@dataclass
class FakeLLM:
    """LLM simulado: responde por tarea con funciones que reciben el prompt del usuario."""

    handlers: dict
    mode: str = "CLOUD_API"
    model: str = "fake/model"
    calls: int = 0
    prompts: list = field(default_factory=list)

    def complete_json(self, system, user, schema, *, deal_id, task):
        self.calls += 1
        self.prompts.append((task, deal_id, user))
        handler = self.handlers.get(task)
        payload = handler(user) if handler else {}
        return schema.model_validate(payload)


def row_ids(prompt: str) -> list[tuple[str, str]]:
    """Extrae (row_id, sugerencia) del prompt del ingestor."""
    return re.findall(r"row_id=(\S+) \| .*? sugerencia regla: (\w+)", prompt)
