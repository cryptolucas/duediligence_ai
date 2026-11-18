"""Casillas de carga, validación de documentos, «Otros archivos» y preparación para pruebas con usuarios."""

from __future__ import annotations

import re


import pytest
from fastapi.testclient import TestClient

from app.agents.context import AgentRuntime, plan_context, run_chunked
from app.agents.graph import run_deal_pipeline
from app.agents.llm_schemas import MemoResponse
from app.main import create_app
from app.schemas.deal import DocumentPage, SourceDocument
from app.services.data_loader import load_benchmarks
from app.services.document_parser import parse_document
from app.services.document_validation import assign_slot, detect_slot, validate_file
from app.services.llm_client import LLMContextTooLarge, LLMError, LLMResolution
from tests.conftest import FakeLLM
from tests.test_pipeline_and_api import DEMO_FILE_IDS, _fake_handlers

TB = "Balance_Prueba_Siigo_2023-2025.xlsx"
EEFF25 = "EEFF_2025_Alimentos_Conservas_Oriente.pdf"
EEFF24 = "EEFF_2024_Alimentos_Conservas_Oriente.pdf"
CERT = "Certificado_Existencia_Representacion_Legal_2025.pdf"
TEASER = "Teaser_Proyecto_Conserva.pdf"
AVALUO = "Avaluo_Canon_Arrendamiento_Bodega_Rionegro.pdf"
SLOTTED = {
    "trial_balance_files": [TB],
    "financial_statements_files": [EEFF25, EEFF24],
    "chamber_certificate_files": [CERT],
    "other_files": [TEASER, AVALUO],
}


def _files(demo_files, mapping=SLOTTED):
    return [(field, (name, (demo_files / name).read_bytes())) for field, names in mapping.items() for name in names]


def _pdf(tmp_path, name, text=None, image_only=False, password=None):
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=9, fontname="helv")
    if image_only:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), 0)
        page.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    path = tmp_path / name
    if password:
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "x")
    else:
        doc.save(path)
    return path


# ---------------------------------------------------------------------------
# Validación por casilla
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, slot, summary_part",
    [
        (TB, "TRIAL_BALANCE", "periodos 2023, 2024, 2025"),
        (EEFF25, "FINANCIAL_STATEMENTS", "años"),
        (CERT, "CHAMBER_CERTIFICATE", "NIT 901.234.567-7"),
        (TEASER, "OTHER", "con información útil"),
    ],
)
def test_demo_documents_are_valid_in_their_slot(demo_files, name, slot, summary_part):
    validation, parsed = validate_file(demo_files / name, slot, name, "doc_x")
    assert validation.status in ("valid", "warning"), validation.issues
    assert summary_part in validation.summary
    assert parsed is not None


def test_document_in_wrong_slot_explains_where_it_goes(demo_files):
    validation, _ = validate_file(demo_files / CERT, "FINANCIAL_STATEMENTS", CERT, "doc_x")
    assert validation.status == "error"
    assert validation.suggested_slot == "CHAMBER_CERTIFICATE"
    assert "casilla 3" in validation.issues[0].fix
    validation, _ = validate_file(demo_files / TEASER, "CHAMBER_CERTIFICATE", TEASER, "doc_x")
    assert validation.status == "error" and validation.suggested_slot == "OTHER"
    # Un balance de prueba en PDF: formato no admitido en la casilla 1, con indicación concreta
    validation, _ = validate_file(demo_files / EEFF25, "TRIAL_BALANCE", EEFF25, "doc_x")
    assert validation.status == "error" and "Excel" in validation.issues[0].fix


def test_primary_document_in_other_files_is_flagged_but_allowed(demo_files):
    validation, _ = validate_file(demo_files / TB, "OTHER", TB, "doc_x")
    assert validation.status == "warning"
    assert validation.suggested_slot == "TRIAL_BALANCE"
    assert "no entran al motor" in validation.issues[0].message


def test_trial_balance_problems(tmp_path):
    no_year = tmp_path / "balance.csv"
    no_year.write_text("Código;Nombre;Saldo final\n1105;Caja;100\n1305;Clientes;200\n4135;Ventas;900\n5105;Personal;50\n6135;Costo;300\n", encoding="utf-8")
    validation, _ = validate_file(no_year, "TRIAL_BALANCE", "balance.csv", "d")
    assert validation.status == "error"
    assert any("año" in i.message for i in validation.issues)

    one_year = tmp_path / "balance_2025.csv"
    one_year.write_text(no_year.read_text(encoding="utf-8"), encoding="utf-8")
    validation, _ = validate_file(one_year, "TRIAL_BALANCE", "balance_2025.csv", "d")
    assert validation.status == "warning" and validation.periods == ["2025"]
    assert any("crecimientos" in i.message for i in validation.issues)

    post_closing = tmp_path / "bp_2025.csv"
    post_closing.write_text("Código;Nombre;Saldo final\n1105;Caja;100\n1305;Clientes;200\n2205;Proveedores;90\n3105;Capital;150\n3605;Utilidad;60\n", encoding="utf-8")
    validation, _ = validate_file(post_closing, "TRIAL_BALANCE", "bp_2025.csv", "d")
    assert any("clase 4" in i.message for i in validation.issues)

    not_tb = tmp_path / "clientes_2025.csv"
    not_tb.write_text("Cliente;Ciudad\nÉxito;Medellín\nD1;Bogotá\n", encoding="utf-8")
    validation, _ = validate_file(not_tb, "TRIAL_BALANCE", "clientes_2025.csv", "d")
    assert validation.status == "error" and "cuentas contables" in validation.issues[0].message


def test_unreadable_files_get_clear_messages(tmp_path):
    empty = tmp_path / "vacio.pdf"
    empty.write_bytes(b"")
    validation, _ = validate_file(empty, "FINANCIAL_STATEMENTS", "vacio.pdf", "d")
    assert validation.status == "error" and "vacío" in validation.issues[0].message

    fake_xlsx = tmp_path / "bp_2025.xlsx"
    fake_xlsx.write_bytes(b"esto no es un excel")
    validation, _ = validate_file(fake_xlsx, "TRIAL_BALANCE", "bp_2025.xlsx", "d")
    assert validation.status == "error" and "dañado" in validation.issues[0].message

    locked = _pdf(tmp_path, "eeff.pdf", "ESTADO DE RESULTADOS 2025", password="secreto")
    validation, _ = validate_file(locked, "FINANCIAL_STATEMENTS", "eeff.pdf", "d")
    assert validation.status == "error" and "contraseña" in validation.issues[0].message

    scanned = _pdf(tmp_path, "escaneado.pdf", image_only=True)
    validation, _ = validate_file(scanned, "CHAMBER_CERTIFICATE", "escaneado.pdf", "d")
    assert validation.status == "error" and "escaneado" in validation.issues[0].message

    photo = tmp_path / "foto.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    validation, _ = validate_file(photo, "OTHER", "foto.jpg", "d")
    assert validation.status == "error" and "PDF digital" in validation.issues[0].fix


def test_financial_statements_without_notes_warns(tmp_path):
    path = _pdf(tmp_path, "eeff.pdf", "ESTADO DE SITUACIÓN FINANCIERA\nActivo | 2025 | 2024\nCaja | 100 | 90\nESTADO DE RESULTADOS\nIngresos | 900 | 800")
    validation, _ = validate_file(path, "FINANCIAL_STATEMENTS", "eeff.pdf", "d")
    assert validation.status == "warning"
    assert any("notas" in i.message for i in validation.issues)


def test_docx_and_txt_other_files_are_read(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_paragraph("Contrato de crédito con Bancolombia: covenant de deuda neta / EBITDA máximo 3,0x.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Cliente", "Participación"
    table.cell(1, 0).text, table.cell(1, 1).text = "Grandes superficies", "48 %"
    path = tmp_path / "contrato.docx"
    doc.save(path)
    validation, parsed = validate_file(path, "OTHER", "contrato.docx", "d")
    assert validation.status == "valid", validation.issues
    assert "covenant" in parsed.source.pages[0].content and "Grandes superficies | 48 %" in parsed.source.pages[0].content

    txt = tmp_path / "receta.txt"
    txt.write_text("Ingredientes: harina, huevos y azúcar. Hornear 30 minutos.", encoding="utf-8")
    validation, _ = validate_file(txt, "OTHER", "receta.txt", "d")
    assert validation.status == "warning" and "no aporte" in validation.issues[0].message


# ---------------------------------------------------------------------------
# API de carga
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(settings):
    return TestClient(create_app(settings))


def test_upload_requirements_and_validate_endpoint(client, demo_files):
    req = client.get("/api/upload-requirements").json()
    slots = {s["id"]: s for s in req["slots"]}
    assert [s for s in slots if slots[s]["required"]] == ["TRIAL_BALANCE", "FINANCIAL_STATEMENTS", "CHAMBER_CERTIFICATE"]
    assert slots["OTHER"]["required"] is False and slots["OTHER"]["examples"]
    response = client.post("/api/documents/validate", data={"slot": "TRIAL_BALANCE"}, files={"file": (TB, (demo_files / TB).read_bytes())})
    body = response.json()
    # El balance demo trae a propósito una celda #REF! (cuenta 2815): se advierte, pero es utilizable
    assert response.status_code == 200 and body["status"] == "warning" and body["periods"] == ["2023", "2024", "2025"]
    assert "no se pudieron leer" in body["issues"][0]["message"]
    response = client.post("/api/documents/validate", data={"slot": "TRIAL_BALANCE"}, files={"file": (CERT, (demo_files / CERT).read_bytes())})
    assert response.json()["status"] == "error"
    assert client.post("/api/documents/validate", data={"slot": "X"}, files={"file": ("a.pdf", b"x")}).status_code == 422


def test_upload_requires_all_mandatory_documents(client, demo_files):
    partial = {k: v for k, v in SLOTTED.items() if k != "chamber_certificate_files"}
    response = client.post("/api/deals/upload", data={"llm_mode": "CLOUD_API"}, files=_files(demo_files, partial))
    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    assert [i["slot"] for i in issues] == ["CHAMBER_CERTIFICATE"]
    assert "Falta" in issues[0]["message"] and issues[0]["fix"]


def test_upload_rejects_invalid_file_and_duplicates(client, demo_files):
    mapping = {**SLOTTED, "chamber_certificate_files": [TEASER], "other_files": [AVALUO, AVALUO]}
    response = client.post("/api/deals/upload", data={"llm_mode": "CLOUD_API"}, files=_files(demo_files, mapping))
    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    assert any(i["file"] == TEASER and i["slot"] == "CHAMBER_CERTIFICATE" for i in issues)
    assert any("mismo archivo" in i["message"] for i in issues)
    too_many = {**SLOTTED, "chamber_certificate_files": [CERT, CERT]}
    assert client.post("/api/deals/upload", data={"llm_mode": "CLOUD_API"}, files=_files(demo_files, too_many)).status_code == 422


def test_upload_by_slots_runs_and_marks_document_roles(settings, demo_files):
    llm = FakeLLM(_fake_handlers())
    client = TestClient(create_app(settings, llm_resolver=lambda mode, s: LLMResolution("CLOUD_API", llm, "fake")))
    response = client.post("/api/deals/upload", data={"llm_mode": "CLOUD_API"}, files=_files(demo_files))
    assert response.status_code == 202, response.text
    deal_id = response.json()["deal_id"]
    view = client.get(f"/api/deals/{deal_id}").json()
    roles = {d["document_name"]: (d["upload_slot"], d["document_type"]) for d in view["dossier"]["documents"]}
    assert roles[TB] == ("TRIAL_BALANCE", "TRIAL_BALANCE_XLSX")
    assert roles[CERT] == ("CHAMBER_CERTIFICATE", "CHAMBER_OF_COMMERCE_CERT")
    assert roles[TEASER][0] == "OTHER" and roles[AVALUO][0] == "OTHER"
    assert view["financials"]["income_statement"][-1]["revenue"]["value_cop"] == 28_150_000_000
    # Los archivos originales no se conservan tras procesar (el texto queda en el expediente)
    assert not (settings.storage_dir / "deals" / deal_id).exists()
    # El analista recibió los documentos etiquetados por rol
    analyst_prompt = next(user for task, _, user in llm.prompts if task == "analyst")
    assert "[FUENTE PRINCIPAL]" in analyst_prompt and "[FUENTE COMPLEMENTARIA" in analyst_prompt


def test_workspace_isolation_and_access_code(settings, demo_files):
    client = TestClient(create_app(settings))
    a = {"X-Workspace-Id": "ws-a"}
    deal_id = client.post("/api/deals/upload", data={"use_demo": "true"}, headers=a).json()["dossier"]["deal_id"]
    assert [d["deal_id"] for d in client.get("/api/deals", headers=a).json()] == [deal_id]
    assert client.get("/api/deals", headers={"X-Workspace-Id": "ws-b"}).json() == []
    assert client.get(f"/api/deals/{deal_id}", headers={"X-Workspace-Id": "ws-b"}).status_code == 200  # enlace directo

    locked = TestClient(create_app(settings.__class__(**{**settings.__dict__, "access_code": "prueba2026"})))
    assert locked.get("/api/health").json()["access_code_required"] is True
    assert locked.get("/api/deals").status_code == 401
    assert locked.get("/api/deals", headers={"X-Access-Code": "otra"}).status_code == 401
    assert locked.get("/api/deals", headers={"X-Access-Code": "prueba2026"}).status_code == 200


def test_background_job_runs_behind_access_code(settings, demo_files):
    client = TestClient(create_app(settings.__class__(**{**settings.__dict__, "access_code": "clave"})))
    headers = {"X-Access-Code": "clave", "X-Workspace-Id": "ws-c"}
    response = client.post("/api/deals/upload", data={"llm_mode": "CLOUD_API"}, files=_files(demo_files), headers=headers)
    assert response.status_code == 202, response.text
    deal_id = response.json()["deal_id"]
    assert client.get(f"/api/deals/{deal_id}/status", headers=headers).json()["status"] == "DONE"
    assert [j["deal_id"] for j in client.get("/api/deals", headers=headers).json()] == [deal_id]


def test_cors_allows_configured_frontend(settings):
    app = create_app(settings.__class__(**{**settings.__dict__, "cors_origins": ("https://catalejo.vercel.app",)}))
    client = TestClient(app)
    preflight = client.options(
        "/api/deals", headers={"Origin": "https://catalejo.vercel.app", "Access-Control-Request-Method": "GET"}
    )
    assert preflight.headers.get("access-control-allow-origin") == "https://catalejo.vercel.app"
    other = client.options("/api/deals", headers={"Origin": "https://otro.com", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in other.headers


# ---------------------------------------------------------------------------
# «Otros archivos»: contexto complementario con salvaguardas
# ---------------------------------------------------------------------------


def _slotted_parsed(demo_files):
    slots = {TB: "TRIAL_BALANCE", EEFF25: "FINANCIAL_STATEMENTS", EEFF24: "FINANCIAL_STATEMENTS", CERT: "CHAMBER_CERTIFICATE", TEASER: "OTHER", AVALUO: "OTHER"}
    return [assign_slot(parse_document(demo_files / name, doc_id, name), slots[name]) for name, doc_id in DEMO_FILE_IDS.items()]


def test_adjustment_from_other_files_stays_pending(demo_files):
    handlers = _fake_handlers()
    base_analyst = handlers["analyst"]

    def analyst(prompt):
        out = base_analyst(prompt)
        out["adjustments"].append(
            {
                "title": "Exceso de arriendo pagado al socio",
                "category": "RELATED_PARTY_RENT",
                "period": "2025",
                "direction": "ADD_BACK",
                "amount_as_reported": 168000000,
                "rationale": "Avalúo",
                "evidence": {"document_id": "doc_avaluo", "page_or_sheet": "Página 1",
                             "exact_quote": "supera el canon de mercado estimado ($330.000.000) en $168.000.000"},
            }
        )
        return out

    llm = FakeLLM({**handlers, "analyst": analyst})
    dossier, result, _ = run_deal_pipeline(
        deal_id="deal-supp", effective_mode="CLOUD_API", benchmarks=load_benchmarks(), llm=llm, parsed_documents=_slotted_parsed(demo_files)
    )
    rent = next(a for a in dossier.ebitda_adjustments if a.category == "RELATED_PARTY_RENT")
    assert rent.status == "PENDING_REVIEW" and "Fuente complementaria" in rent.rationale
    family = next(a for a in dossier.ebitda_adjustments if a.category == "OWNER_COMPENSATION")
    assert family.status == "ACCEPTED"  # nota de los EEFF (fuente principal)
    # El EBITDA ajustado solo incluye lo aceptado: el avalúo no lo mueve hasta que el analista lo valide
    assert result.income_statement[-1].ebitda_adjusted_cop == (2_725 + 312) * 1_000_000


def test_trial_balance_in_other_files_never_feeds_the_engine(demo_files):
    parsed = _slotted_parsed(demo_files)
    extra = assign_slot(parse_document(demo_files / TB, "doc_bp_extra", "copia_bp.xlsx"), "OTHER")
    assert extra.trial_balance_rows == [] and extra.source.document_type == "OTHER"
    dossier, _, _ = run_deal_pipeline(
        deal_id="deal-x", effective_mode="RULES_FALLBACK", benchmarks=load_benchmarks(), parsed_documents=[extra, *parsed]
    )
    assert {a.citation.document_id for a in dossier.mapped_accounts} == {"doc_bp"}


def _doc(doc_id, text, slot=None, doc_type="OTHER", pages=1):
    return SourceDocument(
        document_id=doc_id,
        document_name=f"{doc_id}.pdf",
        document_type=doc_type,
        file_format="PDF",
        description="x",
        reported_units="COP",
        pages=[DocumentPage(page_or_sheet=f"Página {i + 1}", content=text) for i in range(pages)],
        upload_slot=slot,
    )


def test_context_plan_prioritizes_primary_and_drops_irrelevant_pages():
    notes = _doc("eeff", "Nota 12 partes relacionadas: arriendo al accionista. " * 40, "FINANCIAL_STATEMENTS", "FINANCIAL_STATEMENTS_PDF", pages=6)
    teaser = _doc("teaser", "Ventas, EBITDA y clientes principales del negocio. " * 40, "OTHER", "TEASER", pages=6)
    noise = _doc("receta", "Ingredientes: harina, huevos y azúcar. " * 20, "OTHER")
    plan = plan_context([teaser, noise, notes], chunk_chars=6000, max_chunks=2)
    assert plan.irrelevant_supplementary == 1  # la receta no se envía
    assert all("receta" not in c for c in plan.chunks)
    assert plan.chunks[0].startswith("### [FUENTE PRINCIPAL] document_id=eeff")
    # Las complementarias usan como máximo ~35 % del espacio cuando las principales no caben completas
    supp_chars = sum(len(b) for c in plan.chunks for b in c.split("\n\n### ") if "COMPLEMENTARIA" in b)
    assert 0 < supp_chars <= 0.36 * 12000
    assert plan.dropped_primary > 0 and "no se enviaron" in plan.note()


def test_run_chunked_splits_when_provider_says_too_large():
    class SmallModel:
        mode = "CLOUD_API"
        model = "groq/x"
        calls = 0
        max_input_tokens = 9000
        seen: list[int] = []

        def complete_json(self, system, user, schema, *, deal_id, task):
            self.calls += 1
            if len(user) > 9000:
                self.max_input_tokens = 3500
                raise LLMContextTooLarge("muy grande", 4000)
            self.seen.append(len(user))
            return schema(memo_markdown="ok")

    llm = SmallModel()
    runtime = AgentRuntime(deal_id="d", effective_mode="CLOUD_API", benchmarks={}, llm=llm)
    chunk = "\n\n".join(f"### [FUENTE PRINCIPAL] document_id=x | página {i}\n" + "texto " * 300 for i in range(8))
    notes: list[str] = []
    results = run_chunked(
        runtime, system="s", schema=MemoResponse, task="memo", chunks=[chunk], make_user=lambda c, i, n: c, fixed_text="", notes=notes, max_calls=20
    )
    assert len(results) >= 2 and all(size <= 9000 for size in llm.seen)
    assert not notes


def test_run_chunked_keeps_partial_results_when_quota_runs_out():
    class QuotaModel:
        mode, model, calls, max_input_tokens = "CLOUD_API", "groq/x", 0, 9000

        def complete_json(self, system, user, schema, *, deal_id, task):
            self.calls += 1
            if self.calls > 1:
                raise LLMError("límite del plan gratuito alcanzado")
            return schema(memo_markdown="parte 1")

    runtime = AgentRuntime(deal_id="d", effective_mode="CLOUD_API", benchmarks={}, llm=QuotaModel())
    notes: list[str] = []
    results = run_chunked(runtime, system="s", schema=MemoResponse, task="analyst", chunks=["a", "b", "c"], make_user=lambda c, i, n: c, fixed_text="", notes=notes)
    assert [r.memo_markdown for r in results] == ["parte 1"]
    assert "2 quedaron sin analizar" in notes[0]


def test_run_chunked_raises_when_nothing_was_analyzed():
    class Down:
        mode, model, calls, max_input_tokens = "CLOUD_API", "groq/x", 0, 9000

        def complete_json(self, *a, **k):
            raise LLMError("caído")

    runtime = AgentRuntime(deal_id="d", effective_mode="CLOUD_API", benchmarks={}, llm=Down())
    with pytest.raises(LLMError):  # el nodo degrada a reglas deterministas
        run_chunked(runtime, system="s", schema=MemoResponse, task="t", chunks=["a"], make_user=lambda c, i, n: c, fixed_text="", notes=[])


def test_memo_without_engine_placeholders_is_not_trusted(demo_files):
    """Hallazgo de la prueba con un modelo real pequeño: escribió cifras propias y citas '(cit_x)' sin marcadores."""
    calls = []

    def lazy_memo(prompt):
        calls.append(prompt)
        cit = re.search(r"^- (cit_[0-9a-f]{12}):", prompt, flags=re.MULTILINE).group(1)
        return {"memo_markdown": f"# Memo\n\nLa empresa crece 10,9 % ({cit}) con EBITDA de 2.725 millones."}

    llm = FakeLLM({**_fake_handlers(), "memo_writer": lazy_memo})
    dossier, result, log = run_deal_pipeline(
        deal_id="deal-memo", effective_mode="CLOUD_API", benchmarks=load_benchmarks(), llm=llm, parsed_documents=_slotted_parsed(demo_files)
    )
    assert len(calls) == 2 and "CORRECCIÓN" in calls[1]  # se pidió corregir una vez
    assert "10,9 %" not in dossier.memo_markdown_template  # se descartó: plantilla determinista con marcadores
    assert "{{metric:revenue:" in dossier.memo_markdown_template
    memo_notes = next(e for e in log if e["node"] == "node_ic_memo_writer")["notes"]
    assert any("plantilla determinista" in n for n in memo_notes)


def test_loose_citations_are_normalized():
    from app.agents.memo_writer import normalize_citations

    out = normalize_citations("Dato (cit_abc) y [cit_xyz] y [[cite:cit_abc]] y (cit_falsa).", {"cit_abc", "cit_xyz"})
    assert out == "Dato [[cite:cit_abc]] y [[cite:cit_xyz]] y [[cite:cit_abc]] y (cit_falsa)."


def test_detect_slot_on_demo_files(demo_files):
    expected = {TB: "TRIAL_BALANCE", EEFF25: "FINANCIAL_STATEMENTS", EEFF24: "FINANCIAL_STATEMENTS", CERT: "CHAMBER_CERTIFICATE", TEASER: None, AVALUO: None}
    for name, slot in expected.items():
        assert detect_slot(parse_document(demo_files / name, "d", name)) == slot, name
