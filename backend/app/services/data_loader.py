"""Carga y validación de los datos locales (benchmarks sectoriales y expediente demo)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.schemas.deal import DealDossier

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BENCHMARKS_PATH = DATA_DIR / "supersociedades_benchmarks.json"
DEMO_SEED_PATH = DATA_DIR / "demo_deal_seed.json"


@lru_cache(maxsize=1)
def load_benchmarks() -> dict:
    with BENCHMARKS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_demo_dossier() -> DealDossier:
    """Devuelve una copia nueva y validada del expediente demo (cada deal se aísla en su propia instancia)."""
    with DEMO_SEED_PATH.open(encoding="utf-8") as fh:
        return DealDossier.model_validate(json.load(fh))
