"""Grafo multiagente (seed, reglas y LLM simulado) y endpoints FastAPI."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.agents.graph import NODE_SEQUENCE, build_graph, run_deal_pipeline
from app.main import create_app
from app.services.data_loader import load_benchmarks, load_demo_dossier
from app.services.document_parser import parse_document
from app.services.llm_client import LLMResolution, resolve_llm
from app.services.memo_renderer import render_memo
from tests.conftest import FakeLLM, row_ids

M = 1_000_000.0
DEMO_FILE_IDS = {
    "Balance_Prueba_Siigo_2023-2025.xlsx": "doc_bp",
    "EEFF_2025_Alimentos_Conservas_Oriente.pdf": "doc_eeff25",
    "EEFF_2024_Alimentos_Conservas_Oriente.pdf": "doc_eeff24",
    "Certificado_Existencia_Representacion_Legal_2025.pdf": "doc_cc",
    "Teaser_Proyecto_Conserva.pdf": "doc_teaser",
    "Avaluo_Canon_Arrendamiento_Bodega_Rionegro.pdf": "doc_avaluo",
}


def parse_demo_files(folder):
    return [parse_document(folder / name, doc_id, name) for name, doc_id in DEMO_FILE_IDS.items()]


def assert_all_citations_literal(dossier):
    pages = {(d.document_id, p.page_or_sheet): p.content for d in dossier.documents for p in d.pages}
    for c in dossier.iter_citations():
        if c.document_id == "analyst_input":
            continue
        assert c.exact_quote in pages[(c.document_id, c.page_or_sheet)], c


def row(rows, period):
    return next(r for r in rows if r.period == period)


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------


def test_graph_has_five_sequential_nodes():
    names = [n for n, _ in NODE_SEQUENCE]
    assert names == [
        "node_ingestor_and_puc_mapper",
        "node_financial_and_legal_analyst",
        "node_deterministic_financial_engine",
        "node_skeptic_red_team",
        "node_ic_memo_writer",
    ]
    assert set(names) <= set(build_graph().get_graph().nodes)


def test_seed_mode_reproduces_demo_and_runs_engine():
    seed = load_demo_dossier()
    dossier, result, log = run_deal_pipeline(deal_id="demo-x", effective_mode="SEED_FALLBACK", benchmarks=load_benchmarks(), seed=seed)
    assert dossier.deal_id == "demo-x"
    assert dossier.llm_mode == "SEED_FALLBACK"
    assert dossier.mapped_accounts == seed.mapped_accounts
    assert dossier.red_flags == seed.red_flags
    assert row(result.income_statement, "2025").ebitda_adjusted_cop == 3_447 * M
    assert [e["node"] for e in log] == [n for n, _ in NODE_SEQUENCE]
    assert sum(e["llm_calls"] for e in log) == 0


def test_rules_mode_on_real_files_matches_seed_numbers(demo_files):
    parsed = parse_demo_files(demo_files)
    dossier, result, log = run_deal_pipeline(
        deal_id="deal-rules", effective_mode="RULES_FALLBACK", benchmarks=load_benchmarks(), parsed_documents=parsed
    )
    # Mismas cifras que el seed, leídas del Excel real y mapeadas solo con reglas PUC
    inc = row(result.income_statement, "2025")
    assert inc.revenue.value_cop == 28_150 * M
    assert inc.ebitda_reported_cop == 2_725 * M
    assert inc.net_income_cop == 786 * M
    assert inc.ebitda_adjusted_cop == inc.ebitda_reported_cop  # sin LLM no se proponen ajustes
    assert row(result.leverage, "2025").net_financial_debt_cop == 6_705 * M
    # Balance de prueba pre-cierre: el motor suma el resultado del ejercicio y todo cuadra
    assert dossier.pre_closing_trial_balance_periods == ["2023", "2024", "2025"]
    assert all(b.balance_check.is_balanced for b in result.balance_sheet)
    # Identidad desde el certificado de Cámara de Comercio (regex) -> benchmark sectorial
    assert dossier.nit == "901.234.567-7"
    assert dossier.ciiu_code == "1020"
    assert result.valuation.status == "OK"
    # Lo ilegible se reporta, no se inventa
    assert any("2815" in u.description for u in dossier.unreadable_or_unmapped_items)
    # Escéptico por reglas: cartera más lenta y caída de caja
    flag_ids = {f.id for f in dossier.red_flags}
    assert {"rf_rule_cartera", "rf_rule_caja"} <= flag_ids
    assert any(m.id == "mi_rule_accionistas" for m in dossier.missing_info)
    assert_all_citations_literal(dossier)
    memo = render_memo(dossier.memo_markdown_template, result)
    assert "MISSING_DATA" not in memo and "COP 28.150 M" in memo
    assert sum(e["llm_calls"] for e in log) == 0


def _fake_handlers():
    def accounts(prompt):
        return {"items": [{"row_id": rid, "standard_category": cat, "rationale": "ok", "confidence": 0.95} for rid, cat in row_ids(prompt)]}

    def analyst(prompt):
        return {
            "adjustments": [
                {
                    "title": "Salarios de familiares sin cargo operativo",
                    "category": "OWNER_COMPENSATION",
                    "period": "2025",
                    "direction": "ADD_BACK",
                    "amount_as_reported": 312000,
                    "rationale": "Nota 24",
                    "evidence": {"document_id": "doc_eeff25", "page_or_sheet": "Página 9",
                                 "exact_quote": "(cónyuge e hija del accionista mayoritario): $312.000 (2024: $288.000)"},
                },
                {
                    "title": "Ajuste inventado",
                    "category": "OTHER",
                    "period": "2025",
                    "direction": "ADD_BACK",
                    "amount_as_reported": 500000,
                    "rationale": "alucinación",
                    "evidence": {"document_id": "doc_eeff25", "page_or_sheet": "Página 9",
                                 "exact_quote": "Bonificación extraordinaria al gerente por $500.000"},
                },
                {
                    "title": "Honorarios legales con monto equivocado",
                    "category": "NON_RECURRING_LEGAL",
                    "period": "2025",
                    "direction": "ADD_BACK",
                    "amount_as_reported": 999000,
                    "rationale": "Nota 22",
                    "evidence": {"document_id": "doc_eeff25", "page_or_sheet": "Página 7",
                                 "exact_quote": "pagó honorarios de defensa a la firma de abogados externa por $280.000"},
                },
            ],
            "nit": {"value": "901.234.567-7", "evidence": {"document_id": "doc_cc", "page_or_sheet": "Página 1", "exact_quote": "NIT: 901.234.567-7"}},
            "ciiu_primary": {"value": "1020", "evidence": {"document_id": "doc_cc", "page_or_sheet": "Página 1", "exact_quote": "Código CIIU 1020"}},
            "legal_name": {"value": "Alimentos y Conservas del Oriente S.A.S.", "evidence": {"document_id": "doc_cc", "page_or_sheet": "Página 1", "exact_quote": "Razón social: ALIMENTOS Y CONSERVAS DEL ORIENTE S.A.S."}},
            "shareholders": [
                {"name": "Jorge Enrique Ramírez Gómez", "ownership_pct": 60, "evidence": {"document_id": "doc_teaser", "page_or_sheet": "Página 2", "exact_quote": "Jorge Enrique Ramírez Gómez 60 %"}}
            ],
            "legal_proceedings": [
                {"proceeding_type": "LABORAL", "description": "Contrato realidad", "claimed_amount_as_reported": 850000,
                 "probability": "POSIBLE", "evidence": {"document_id": "doc_eeff25", "page_or_sheet": "Página 7", "exact_quote": "Las pretensiones ascienden a $850.000."}}
            ],
        }

    def skeptic(prompt):
        return {
            "red_flags": [
                {"severity": "HIGH", "domain": "FINANCIAL", "title": "Cliente en reorganización", "challenge_by_skeptic": "x",
                 "mitigation_question": "y", "evidence": [{"document_id": "doc_eeff25", "page_or_sheet": "Página 4",
                                                           "exact_quote": "admitida a proceso de reorganización empresarial (Ley 1116 de 2006)"}]},
                {"severity": "CRITICAL_DEALBREAKER", "domain": "FINANCIAL", "title": "Fraude inventado", "challenge_by_skeptic": "x",
                 "mitigation_question": "y", "evidence": [{"document_id": "doc_eeff25", "page_or_sheet": "Página 4", "exact_quote": "El gerente desvió fondos a paraísos fiscales"}]},
            ],
            "missing_info": [{"category": "Societario", "requested_document_or_clarification": "Libro de accionistas",
                              "why_it_matters_plain_spanish": "Para saber quién es dueño.", "priority": "MUST_HAVE_FOR_IC"}],
        }

    def memo(prompt):
        real_id = re.search(r"^- (cit_[0-9a-f]{12}):", prompt, flags=re.MULTILINE).group(1)
        return {"memo_markdown": f"# Memo\n\nIngresos {{{{metric:revenue:2025}}}} [[cite:{real_id}]] [[cite:cit_inventada]]."}

    return {
        "ingestor.accounts": accounts,
        "ingestor.statements": lambda prompt: {"items": []},
        "analyst": analyst,
        "skeptic": skeptic,
        "memo_writer": memo,
    }


def test_llm_mode_guards_against_hallucinations(demo_files):
    llm = FakeLLM(_fake_handlers())
    dossier, result, log = run_deal_pipeline(
        deal_id="deal-llm", effective_mode="CLOUD_API", benchmarks=load_benchmarks(), llm=llm, parsed_documents=parse_demo_files(demo_files)
    )
    assert llm.calls == 5  # cuentas ambiguas, EEFF PDF, analista, escéptico, redactor
    assert all(deal_id == "deal-llm" for _, deal_id, _ in llm.prompts)  # aislamiento por operación
    adjustments = {a.title: a for a in dossier.ebitda_adjustments}
    # Ajuste válido: monto convertido de miles a COP por código, no por el LLM
    fam = adjustments["Salarios de familiares sin cargo operativo"]
    assert fam.amount_cop == 312 * M and fam.status == "ACCEPTED"
    # Cita alucinada -> descartado
    assert "Ajuste inventado" not in adjustments
    # Monto que no aparece en la cita -> queda pendiente de revisión
    legal = adjustments["Honorarios legales con monto equivocado"]
    assert legal.status == "PENDING_REVIEW" and legal.rationale.startswith("⚠")
    assert row(result.income_statement, "2025").ebitda_adjusted_cop == (2_725 + 312) * M
    # Perfil societario: teaser = no verificado; certificado = verificado
    assert dossier.corporate_profile.shareholders[0].verification_status == "UNVERIFIED"
    assert dossier.corporate_profile.nit.status == "VERIFIED"
    assert dossier.corporate_profile.legal_proceedings[0].claimed_amount_cop == 850 * M
    assert result.contingencies.unprovisioned_probable_or_possible_cop == 850 * M
    # Red flag sin evidencia literal -> descartada
    titles = {f.title for f in dossier.red_flags}
    assert "Cliente en reorganización" in titles and "Fraude inventado" not in titles
    # Memo: cita inventada removida, marcador resuelto por el motor
    assert "cit_inventada" not in dossier.memo_markdown_template
    assert "⟦cita no verificada⟧" in dossier.memo_markdown_template
    assert "COP 28.150 M" in render_memo(dossier.memo_markdown_template, result)
    assert_all_citations_literal(dossier)
    engine_entry = next(e for e in log if e["node"] == "node_deterministic_financial_engine")
    assert engine_entry["llm_calls"] == 0


def test_ollama_unavailable_never_falls_back_to_cloud(settings):
    cloud_settings = settings.__class__(**{**settings.__dict__, "api_keys": {"OPENAI_API_KEY": "sk-test"}})
    resolution = resolve_llm("LOCAL_OLLAMA", cloud_settings)
    assert resolution.effective_mode == "RULES_FALLBACK"
    assert resolution.client is None
    assert "confidencialidad" in resolution.reason
    assert resolve_llm("CLOUD_API", settings).effective_mode == "RULES_FALLBACK"  # sin claves
    cloud = resolve_llm("CLOUD_API", cloud_settings)
    assert cloud.effective_mode == "CLOUD_API" and cloud.client.model == "openai/gpt-4.1"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(settings):
    return TestClient(create_app(settings))


@pytest.fixture()
def demo_deal(client):
    response = client.post("/api/deals/upload", data={"use_demo": "true"})
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_demo_and_get(client, demo_deal):
    deal_id = demo_deal["dossier"]["deal_id"]
    assert deal_id.startswith("demo-")
    assert "COP 3.447 M" in demo_deal["memo_markdown"]
    listing = client.get("/api/deals").json()
    assert listing[0]["deal_id"] == deal_id
    assert listing[0]["ebitda_adjusted_last_cop"] == 3_447 * M
    assert listing[0]["red_flags_by_severity"]["CRITICAL_DEALBREAKER"] == 1
    view = client.get(f"/api/deals/{deal_id}").json()
    assert view["dossier"]["company_name"] == "Alimentos y Conservas del Oriente S.A.S."
    assert client.get("/api/deals/no-existe").status_code == 404


def test_each_demo_upload_is_an_isolated_deal(client):
    a = client.post("/api/deals/upload", data={"use_demo": "true"}).json()["dossier"]["deal_id"]
    b = client.post("/api/deals/upload", data={"use_demo": "true"}).json()["dossier"]["deal_id"]
    assert a != b
    client.post(f"/api/deals/{a}/recalculate", json={"adjustment_statuses": {"adj_2025_legal": "REJECTED"}})
    statuses_b = {x["id"]: x["status"] for x in client.get(f"/api/deals/{b}").json()["dossier"]["ebitda_adjustments"]}
    assert statuses_b["adj_2025_legal"] == "ACCEPTED"


def test_recalculate_toggle_persists_and_is_fast(client, demo_deal):
    deal_id = demo_deal["dossier"]["deal_id"]
    response = client.post(f"/api/deals/{deal_id}/recalculate", json={"adjustment_statuses": {"adj_2025_legal": "REJECTED"}})
    assert response.status_code == 200
    data = response.json()
    inc = next(r for r in data["financials"]["income_statement"] if r["period"] == "2025")
    assert inc["ebitda_adjusted_cop"] == 3_167 * M
    assert "COP 3.167 M" in data["memo_markdown"]
    assert data["computation_ms"] < 100
    view = client.get(f"/api/deals/{deal_id}").json()
    status = {a["id"]: a["status"] for a in view["dossier"]["ebitda_adjustments"]}
    assert status["adj_2025_legal"] == "REJECTED"


def test_recalculate_without_persist(client, demo_deal):
    deal_id = demo_deal["dossier"]["deal_id"]
    client.post(f"/api/deals/{deal_id}/recalculate", json={"adjustment_statuses": {"adj_2025_rent": "REJECTED"}, "persist": False})
    status = {a["id"]: a["status"] for a in client.get(f"/api/deals/{deal_id}").json()["dossier"]["ebitda_adjustments"]}
    assert status["adj_2025_rent"] == "ACCEPTED"


def test_manual_adjustments_and_red_flags(client, demo_deal):
    deal_id = demo_deal["dossier"]["deal_id"]
    body = {
        "manual_adjustments": [
            {"title": "Bono extraordinario 2025", "category": "OTHER", "period": "2025", "amount_cop": 50_000_000,
             "rationale": "Confirmado por el gerente en llamada del 10-nov"},
            {"title": "Exceso arriendo según avalúo", "category": "RELATED_PARTY_RENT", "period": "2025", "amount_cop": 1_000_000,
             "rationale": "Prueba de cita", "status": "REJECTED",
             "evidence": {"document_id": "doc_avaluo_bodega", "page_or_sheet": "Página 3", "exact_quote": "supera el canon de mercado estimado ($330.000.000)"}},
        ],
        "red_flag_statuses": {"rf_concentracion": "DISMISSED"},
    }
    data = client.post(f"/api/deals/{deal_id}/recalculate", json=body).json()
    manual = [a for a in data["ebitda_adjustments"] if a["origin"] == "ANALYST_MANUAL"]
    assert len(manual) == 2
    assert manual[0]["citation"]["document_id"] == "analyst_input"
    assert manual[1]["citation"]["page_or_sheet"] == "Página 3"
    inc = next(r for r in data["financials"]["income_statement"] if r["period"] == "2025")
    assert inc["ebitda_adjusted_cop"] == 3_497 * M
    assert next(f for f in data["red_flags"] if f["id"] == "rf_concentracion")["status"] == "DISMISSED"
    # Eliminar el manual restaura el EBITDA; los ajustes de la IA no se eliminan, se rechazan
    removed = client.post(f"/api/deals/{deal_id}/recalculate", json={"remove_adjustment_ids": [manual[0]["id"]]}).json()
    assert next(r for r in removed["financials"]["income_statement"] if r["period"] == "2025")["ebitda_adjusted_cop"] == 3_447 * M
    assert client.post(f"/api/deals/{deal_id}/recalculate", json={"remove_adjustment_ids": ["adj_2025_rent"]}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"adjustment_statuses": {"no_existe": "REJECTED"}},
        {"red_flag_statuses": {"rf_no_existe": "DISMISSED"}},
        {"manual_adjustments": [{"title": "X periodo", "period": "2019", "amount_cop": 1, "rationale": "abc"}]},
        {"manual_adjustments": [{"title": "Cita falsa", "period": "2025", "amount_cop": 1, "rationale": "abc",
                                 "evidence": {"document_id": "doc_eeff_2025", "page_or_sheet": "Página 3", "exact_quote": "texto que no existe en ningún documento"}}]},
    ],
)
def test_recalculate_rejects_invalid_requests(client, demo_deal, body):
    assert client.post(f"/api/deals/{demo_deal['dossier']['deal_id']}/recalculate", json=body).status_code == 422


def test_chat_simulates_scenario_without_llm(client, demo_deal):
    deal_id = demo_deal["dossier"]["deal_id"]
    data = client.post(f"/api/deals/{deal_id}/chat", json={"message": "¿Qué pasa con el EBITDA si excluimos el arriendo pagado al socio?"}).json()
    scenario = data["scenario"]
    assert scenario["overrides"] == {"adj_2025_rent": "REJECTED"}  # ya estaba aceptado: se muestra revertirlo
    assert scenario["before"]["ebitda_adjusted_cop"] == 3_447 * M
    assert scenario["after"]["ebitda_adjusted_cop"] == 3_279 * M
    assert scenario["after"]["base_enterprise_value_cop"] == pytest.approx(6.0 * 3_279 * M)
    assert any(c["citation_id"] == "cit_avaluo_2025" for c in data["citations"])
    # La simulación no modifica el expediente
    status = {a["id"]: a["status"] for a in client.get(f"/api/deals/{deal_id}").json()["dossier"]["ebitda_adjustments"]}
    assert status["adj_2025_rent"] == "ACCEPTED"
    history = client.get(f"/api/deals/{deal_id}").json()["chat_history"]
    assert [h["role"] for h in history] == ["user", "assistant"]


def test_chat_finds_sources(client, demo_deal):
    deal_id = demo_deal["dossier"]["deal_id"]
    data = client.post(f"/api/deals/{deal_id}/chat", json={"message": "¿De dónde sale el dato de la demanda laboral?"}).json()
    ids = {c["citation_id"] for c in data["citations"]}
    assert ids & {"cit_n22_pretensiones", "cit_n22_cooperativa", "cit_n22_honorarios"}
    summary = client.post(f"/api/deals/{deal_id}/chat", json={"message": "Hola, dame un resumen"}).json()
    assert "COP 28.150 M" in summary["answer_markdown"]


def upload_demo_files(client, demo_files, mode="CLOUD_API"):
    files = [("files", (name, (demo_files / name).read_bytes())) for name in DEMO_FILE_IDS]
    return client.post("/api/deals/upload", data={"llm_mode": mode}, files=files)


def test_upload_real_files_runs_in_background_with_progress(client, demo_files):
    response = upload_demo_files(client, demo_files, "LOCAL_OLLAMA")
    assert response.status_code == 202, response.text
    accepted = response.json()
    deal_id = accepted["deal_id"]
    assert deal_id.startswith("deal-")
    assert accepted["effective_mode"] == "RULES_FALLBACK" and "confidencialidad" in accepted["mode_reason"]
    assert len(accepted["document_names"]) == 6
    # TestClient ejecuta la tarea de fondo antes de devolver la respuesta: el job ya terminó.
    status = client.get(f"/api/deals/{deal_id}/status").json()
    assert status["status"] == "DONE" and status["progress_pct"] == 100
    assert [s["state"] for s in status["steps"]] == ["done"] * 5
    kinds = [e["type"] for e in status["events"]]
    assert kinds[0] == "info" and kinds[-1] == "done"
    assert kinds.count("node_started") == 5 and kinds.count("node_finished") == 5
    view = client.get(f"/api/deals/{deal_id}").json()
    assert view["dossier"]["llm_mode"] == "RULES_FALLBACK"
    assert view["requested_mode"] == "LOCAL_OLLAMA"
    assert all(b["balance_check"]["is_balanced"] for b in view["financials"]["balance_sheet"])
    assert view["processing_log"][0]["node"] == "llm_resolution"
    assert client.get("/api/jobs").json() == []  # solo lista jobs en curso o fallidos


def test_failed_background_job_is_reported(settings, demo_files):
    def boom(prompt):
        raise RuntimeError("el modelo se cayó")

    llm = FakeLLM({**_fake_handlers(), "analyst": boom})
    client = TestClient(create_app(settings, llm_resolver=lambda mode, s: LLMResolution("CLOUD_API", llm, "fake")))
    deal_id = upload_demo_files(client, demo_files).json()["deal_id"]
    status = client.get(f"/api/deals/{deal_id}/status").json()
    assert status["status"] == "FAILED"
    assert "el modelo se cayó" in status["error"]
    states = {s["node"]: s["state"] for s in status["steps"]}
    assert states["node_ingestor_and_puc_mapper"] == "done"
    assert states["node_financial_and_legal_analyst"] == "failed"
    assert client.get(f"/api/deals/{deal_id}").status_code == 409
    assert [j["deal_id"] for j in client.get("/api/jobs").json()] == [deal_id]
    assert not (settings.storage_dir / "deals" / deal_id).exists()


def test_interrupted_jobs_are_failed_on_restart(settings):
    first = create_app(settings)
    first.state.repo.create_job("deal-colgado", "CLOUD_API", "CLOUD_API", "x", ["a.pdf"])
    client = TestClient(create_app(settings))  # "reinicio" del servidor con la misma base
    status = client.get("/api/deals/deal-colgado/status").json()
    assert status["status"] == "FAILED" and "reinició" in status["error"]


def test_pipeline_emits_progress_and_llm_call_events(demo_files):
    events = []
    llm = FakeLLM(_fake_handlers())
    run_deal_pipeline(
        deal_id="deal-ev",
        effective_mode="CLOUD_API",
        benchmarks=load_benchmarks(),
        llm=llm,
        parsed_documents=parse_demo_files(demo_files),
        on_progress=events.append,
    )
    started = [e["node"] for e in events if e["type"] == "node_started"]
    finished = [e["node"] for e in events if e["type"] == "node_finished"]
    assert started == finished == [n for n, _ in NODE_SEQUENCE]
    llm_tasks = [e["task"] for e in events if e["type"] == "llm_call"]
    assert llm_tasks == ["ingestor.accounts", "ingestor.statements", "analyst", "skeptic", "memo_writer"]
    assert llm.calls == 5


def test_deal_status_for_demo_and_unknown(client, demo_deal):
    status = client.get(f"/api/deals/{demo_deal['dossier']['deal_id']}/status").json()
    assert status["status"] == "DONE"
    assert client.get("/api/deals/no-existe/status").status_code == 404


def test_upload_with_fake_cloud_llm(settings, demo_files):
    llm = FakeLLM(_fake_handlers())
    app = create_app(settings, llm_resolver=lambda mode, s: LLMResolution("CLOUD_API", llm, "fake"))
    client = TestClient(app)
    deal_id = upload_demo_files(client, demo_files).json()["deal_id"]
    view = client.get(f"/api/deals/{deal_id}").json()
    assert view["dossier"]["llm_mode"] == "CLOUD_API"
    ids = {f"doc_{i:02d}" for i in range(1, 7)}
    assert {d["document_id"][:6] for d in view["dossier"]["documents"]} == ids
    # El chat de un deal cloud usa el LLM; aquí devuelve un escenario que el motor recalcula
    adj_id = view["dossier"]["ebitda_adjustments"][0]["id"]
    llm.handlers["chat"] = lambda prompt: {"answer_markdown": "EBITDA {{metric:ebitda_adjusted:2025}}", "scenario_overrides": {adj_id: "REJECTED", "fantasma": "ACCEPTED"}}
    chat = client.post(f"/api/deals/{deal_id}/chat", json={"message": "¿y si rechazo el ajuste de familiares?"}).json()
    assert chat["mode"] == "LLM"
    assert chat["scenario"]["overrides"] == {adj_id: "REJECTED"}
    assert "COP 2.725 M" in chat["answer_markdown"]  # marcador resuelto contra el escenario


@pytest.mark.parametrize(
    "files, data, status",
    [
        ([], {"llm_mode": "CLOUD_API"}, 422),
        ([("files", ("contrato.docx", b"x"))], {"llm_mode": "CLOUD_API"}, 415),
        ([("files", ("notas.csv", b"solo texto sin cifras"))], {"llm_mode": "CLOUD_API"}, 422),
        ([("files", ("bp.csv", b"Cuenta;Saldo\n1105;100"))], {"llm_mode": "OTRO"}, 422),
    ],
)
def test_upload_validation(client, files, data, status):
    assert client.post("/api/deals/upload", data=data, files=files or None).status_code == status


def test_llm_status_and_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
    status = client.get("/api/llm/status").json()
    assert status["cloud_available"] is False and status["ollama_available"] is False


def test_only_ambiguous_accounts_are_sent_to_the_llm(demo_files):
    llm = FakeLLM(_fake_handlers())
    run_deal_pipeline(
        deal_id="deal-amb", effective_mode="CLOUD_API", benchmarks=load_benchmarks(), llm=llm, parsed_documents=parse_demo_files(demo_files)
    )
    prompt = next(user for task, _, user in llm.prompts if task == "ingestor.accounts")
    assert "código 1380 " in prompt and "código 2355 " in prompt  # deudores varios / deudas con socios: ambiguas
    assert "código 1105 " not in prompt and "código 4120 " not in prompt and "código 6120 " not in prompt
    assert len(row_ids(prompt)) < 60
