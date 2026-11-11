"""Integridad del caso semilla y de la regla Zero Uncited Claims.

* Toda cita apunta a un documento y página existentes y su ``exact_quote`` es literal.
* Los valores de cuentas y ajustes se pueden reproducir desde la cita (no hay cifras huérfanas).
* El memo solo referencia citas existentes y todos sus marcadores se resuelven con el motor.
* El JSON versionado coincide con lo que produce el generador.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.deal import CitedFact, RedFlagItem, SourceCitation
from app.services.data_loader import DEMO_SEED_PATH, load_benchmarks, load_demo_dossier
from app.services.financial_engine import recalculate_dossier
from app.services.memo_renderer import extract_citation_ids, extract_placeholders, render_memo

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dossier():
    return load_demo_dossier()


def _page(dossier, document_id: str, page: str) -> str:
    doc = next(d for d in dossier.documents if d.document_id == document_id)
    return next(p.content for p in doc.pages if p.page_or_sheet == page)


def _number_variants(value_cop: float) -> set[str]:
    """Representaciones literales esperables de un monto: miles de COP (EEFF) o COP plenos (Excel/avalúo)."""
    pesos = int(round(abs(value_cop)))
    variants = {f"{pesos:,}".replace(",", ".")}
    if pesos % 1000 == 0:
        variants.add(f"{pesos // 1000:,}".replace(",", "."))
    return variants


def test_every_citation_is_literal_in_its_document(dossier):
    citations = list(dossier.iter_citations())
    assert len(citations) > 100
    for c in citations:
        assert c.exact_quote in _page(dossier, c.document_id, c.page_or_sheet), c.citation_id
        doc_name = next(d.document_name for d in dossier.documents if d.document_id == c.document_id)
        assert c.document_name == doc_name


def test_citation_ids_are_consistent(dossier):
    seen: dict[str, SourceCitation] = {}
    for c in dossier.iter_citations():
        if c.citation_id in seen:
            assert seen[c.citation_id] == c, f"{c.citation_id} reutilizado con contenido distinto"
        seen[c.citation_id] = c


def test_mapped_account_values_are_reproducible_from_quote(dossier):
    for item in dossier.mapped_accounts:
        quote = item.citation.exact_quote
        assert any(v in quote for v in _number_variants(item.raw_value_cop)), (item.raw_account_code, item.period, quote)
        if item.citation.document_id == "doc_bp_siigo":
            assert quote.startswith(f"{item.raw_account_code} |")
            assert item.citation.page_or_sheet == f"BP_{item.period}"
            assert re.fullmatch(r"C\d+", item.citation.cell_or_line_ref or "")


def test_adjustment_amounts_are_quoted_literally(dossier):
    for adj in dossier.ebitda_adjustments:
        assert any(v in adj.citation.exact_quote for v in _number_variants(adj.amount_cop)), adj.id


def test_contingency_amounts_are_quoted_literally(dossier):
    for proc in dossier.corporate_profile.legal_proceedings:
        assert proc.claimed_amount_cop is not None
        assert any(v in proc.citation.exact_quote for v in _number_variants(proc.claimed_amount_cop)), proc.id


def test_seed_has_expected_shape(dossier):
    assert dossier.company_name == "Alimentos y Conservas del Oriente S.A.S."
    assert dossier.ciiu_code == "1020"
    assert dossier.periods == ["2023", "2024", "2025"]
    categories = {a.category for a in dossier.ebitda_adjustments}
    assert {"OWNER_COMPENSATION", "RELATED_PARTY_RENT", "NON_RECURRING_LEGAL", "PERSONAL_EXPENSES"} <= categories
    assert {a.status for a in dossier.ebitda_adjustments} == {"ACCEPTED", "PENDING_REVIEW"}
    assert any(rf.severity == "CRITICAL_DEALBREAKER" for rf in dossier.red_flags)
    assert any(mi.priority == "MUST_HAVE_FOR_IC" for mi in dossier.missing_info)
    assert any(p.proceeding_type == "LABORAL" for p in dossier.corporate_profile.legal_proceedings)
    assert len(dossier.unreadable_or_unmapped_items) >= 1


def test_nit_check_digit_is_valid(dossier):
    base, dv = dossier.nit.replace(".", "").split("-")
    weights = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    rem = sum(int(d) * w for d, w in zip(reversed(base), weights)) % 11
    assert int(dv) == (rem if rem in (0, 1) else 11 - rem)


def test_memo_references_only_existing_citations(dossier):
    index = dossier.citation_index()
    ids = extract_citation_ids(dossier.memo_markdown_template)
    assert len(ids) >= 20
    missing = sorted(set(ids) - set(index))
    assert not missing, missing


def test_memo_placeholders_all_resolve_and_follow_toggles(dossier):
    benchmarks = load_benchmarks()
    assert extract_placeholders(dossier.memo_markdown_template)
    _, base = recalculate_dossier(dossier, benchmarks)
    rendered = render_memo(dossier.memo_markdown_template, base)
    assert "MISSING_DATA" not in rendered
    assert "{{" not in rendered
    assert "COP 3.447 M" in rendered  # EBITDA ajustado 2025
    _, toggled = recalculate_dossier(dossier, benchmarks, {"adj_2025_legal": "REJECTED"})
    rendered_toggled = render_memo(dossier.memo_markdown_template, toggled)
    assert "COP 3.167 M" in rendered_toggled
    assert "COP 3.447 M" not in rendered_toggled


def test_memo_unknown_placeholder_is_flagged_not_invented(dossier):
    _, result = recalculate_dossier(dossier, load_benchmarks())
    out = render_memo("EBITDA 2031: {{metric:ebitda_adjusted:2031}}", result)
    assert out == "EBITDA 2031: ⟦MISSING_DATA: metric:ebitda_adjusted:2031⟧"


def test_seed_file_matches_generator_output():
    spec = importlib.util.spec_from_file_location("build_demo_seed", BACKEND_DIR / "scripts" / "build_demo_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated = module.DealDossier.model_validate(module.seed).model_dump(mode="json")
    on_disk = json.loads(DEMO_SEED_PATH.read_text(encoding="utf-8"))
    assert generated == on_disk, "Regenerar con: python scripts/build_demo_seed.py"


# ---------------------------------------------------------------------------
# Esquemas: las afirmaciones sin fuente se rechazan
# ---------------------------------------------------------------------------


def test_cited_fact_without_citation_must_be_missing_data():
    with pytest.raises(ValidationError):
        CitedFact(label="NIT", value="900.000.000-1", status="VERIFIED")
    fact = CitedFact(label="Libro de accionistas", status="MISSING_DATA")
    assert fact.value is None


def test_red_flag_requires_at_least_one_citation():
    with pytest.raises(ValidationError):
        RedFlagItem(
            id="rf",
            severity="HIGH",
            domain="FINANCIAL",
            title="x",
            challenge_by_skeptic="x",
            mitigation_question="x",
            citations=[],
        )


def test_citation_confidence_bounds():
    with pytest.raises(ValidationError):
        SourceCitation(citation_id="c", document_id="d", document_name="n", page_or_sheet="p", exact_quote="q", confidence=1.5)


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


def test_benchmarks_are_consistent():
    data = load_benchmarks()
    sectors = data["sectors"]
    assert set(sectors) == {"AGROINDUSTRIA", "MANUFACTURA_ALIMENTOS", "SERVICIOS_B2B", "COMERCIO_MAYORISTA", "LOGISTICA"}
    for key, sector in sectors.items():
        for block in [sector["ev_ebitda"], sector["ev_revenue"], *sector["operating_benchmarks"].values()]:
            assert block["p25"] <= block["median"] <= block["p75"], key
    for code, entry in data["ciiu_catalog"].items():
        assert re.fullmatch(r"\d{4}", code)
        assert entry["sector_key"] in sectors
    assert set(data["ciiu_division_fallback"].values()) <= set(sectors)


# ---------------------------------------------------------------------------
# API mínima
# ---------------------------------------------------------------------------


def test_api_health_and_benchmarks(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/benchmarks").json()["_meta"]["status"] == "REFERENCIAL_NO_OFICIAL"
