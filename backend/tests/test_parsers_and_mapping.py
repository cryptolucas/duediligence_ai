"""Parsers documentales, lectura de cifras, mapeo PUC y guardián de citas."""

from __future__ import annotations

import pytest

from app.services.citation_guard import find_literal, verify_quote
from app.services.document_parser import UnsupportedDocumentError, parse_document
from app.services.numbers import amount_supported_by_text, find_numbers, parse_number
from app.services.puc_mapper import detect_sign_convention, is_pre_closing, rule_based_mapping, to_engine_value

# ---------------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("28.790.000.000,00", 28_790_000_000.0),
        ("-28.790.000.000,00", -28_790_000_000.0),
        ("(1.234)", -1234.0),
        ("1,234.50", 1234.5),
        ("1.234,5", 1234.5),
        ("$ 45.000", 45_000.0),
        ("COP 3.900", 3_900.0),
        ("0,00", 0.0),
        ("12,5", 12.5),
        ("1.5", 1.5),
        (850000.0, 850000.0),
        ("#¡REF!", None),
        ("#REF!", None),
        ("Clientes", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_find_numbers_and_amount_support():
    text = "Las pretensiones ascienden a $850.000. (Nota 22)"
    values = [v for _, v in find_numbers(text)]
    assert 850_000.0 in values
    assert amount_supported_by_text(850_000_000, text)  # miles de COP
    assert amount_supported_by_text(850_000, text)
    assert not amount_supported_by_text(851_000_000, text)


# ---------------------------------------------------------------------------
# Mapeo PUC y signos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, name, category",
    [
        ("110505", "Caja general", "CASH"),
        ("130505", "Clientes nacionales", "ACCOUNTS_RECEIVABLE"),
        ("1399", "Deterioro", "ACCOUNTS_RECEIVABLE"),
        ("1380", "Deudores varios", "OTHER_CURRENT_ASSETS"),
        ("1455", "Envases", "INVENTORY"),
        ("1592", "Depreciación acumulada", "PPE_AND_INTANGIBLES"),
        ("1910", "Valorizaciones", "UNMAPPED"),
        ("21051001", "Pagarés corto plazo", "SHORT_TERM_DEBT"),
        ("21051002", "Pagarés bancarios - largo plazo", "LONG_TERM_DEBT"),
        ("2355", "Deudas con accionistas", "LONG_TERM_DEBT"),
        ("2205", "Proveedores", "ACCOUNTS_PAYABLE"),
        ("2404", "Renta por pagar", "OTHER_CURRENT_LIABILITIES"),
        ("3605", "Utilidad del ejercicio", "EQUITY"),
        ("3805", "Superávit por valorizaciones", "UNMAPPED"),
        ("4120", "Industrias manufactureras", "REVENUE"),
        ("4175", "Devoluciones", "REVENUE"),
        ("4210", "Financieros", "NET_INTEREST"),
        ("4250", "Recuperaciones", "OTHER_OP_INCOME_EXP"),
        ("5105", "Gastos de personal", "SGA"),
        ("5160", "Depreciaciones", "DA"),
        ("5260", "Depreciaciones ventas", "DA"),
        ("5305", "Financieros", "NET_INTEREST"),
        ("5315", "Extraordinarios", "OTHER_OP_INCOME_EXP"),
        ("5405", "Impuesto de renta", "TAXES"),
        ("6120", "Costo de ventas", "COGS"),
        ("7105", "Materia prima", "UNMAPPED"),
        ("8105", "Cuentas de orden", "UNMAPPED"),
    ],
)
def test_rule_based_mapping(code, name, category):
    assert rule_based_mapping(code, name).category == category


def test_sign_normalization_debit_positive_export():
    # Siigo: saldos crédito negativos
    assert to_engine_value("4120", "REVENUE", -100.0, "DEBIT_POSITIVE") == 100.0
    assert to_engine_value("4175", "REVENUE", 10.0, "DEBIT_POSITIVE") == -10.0
    assert to_engine_value("2205", "ACCOUNTS_PAYABLE", -50.0, "DEBIT_POSITIVE") == 50.0
    assert to_engine_value("1592", "PPE_AND_INTANGIBLES", -30.0, "DEBIT_POSITIVE") == -30.0
    assert to_engine_value("4210", "NET_INTEREST", -5.0, "DEBIT_POSITIVE") == -5.0
    assert to_engine_value("5315", "OTHER_OP_INCOME_EXP", 7.0, "DEBIT_POSITIVE") == -7.0


def test_sign_normalization_natural_positive_export():
    # Todo positivo según su naturaleza: las correctoras se identifican por código
    assert to_engine_value("4120", "REVENUE", 100.0, "NATURAL_POSITIVE") == 100.0
    assert to_engine_value("4175", "REVENUE", 10.0, "NATURAL_POSITIVE") == -10.0
    assert to_engine_value("1592", "PPE_AND_INTANGIBLES", 30.0, "NATURAL_POSITIVE") == -30.0
    assert to_engine_value("2205", "ACCOUNTS_PAYABLE", 50.0, "NATURAL_POSITIVE") == 50.0
    assert to_engine_value("4210", "NET_INTEREST", 5.0, "NATURAL_POSITIVE") == -5.0
    assert to_engine_value("5315", "OTHER_OP_INCOME_EXP", 7.0, "NATURAL_POSITIVE") == -7.0


def test_detect_convention_and_pre_closing():
    assert detect_sign_convention([("4120", -100.0), ("2205", -50.0), ("1105", 10.0)]) == "DEBIT_POSITIVE"
    assert detect_sign_convention([("4120", 100.0), ("2205", 50.0), ("1105", 10.0)]) == "NATURAL_POSITIVE"
    assert is_pre_closing(["1105", "4120", "5105"])
    assert not is_pre_closing(["1105", "3605", "4120"])
    assert not is_pre_closing(["1105", "2205", "3105"])


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_xlsx_trial_balance_with_hierarchy(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Balance"
    ws["A1"] = "EMPRESA DEMO S.A.S."
    ws["A2"] = "Balance de prueba a 31/12/2024"
    ws.append([])
    ws.append(["Código", "Nombre de la cuenta", "Saldo anterior", "Saldo final"])
    rows = [
        ("1", "ACTIVO", 0, 1500),
        ("11", "DISPONIBLE", 0, 1500),
        ("1105", "CAJA", 0, 1500),
        ("110505", "Caja general", 0, 1000),
        ("110510", "Cajas menores", 0, 500),
        ("4135", "Comercio al por mayor", 0, -2000),
        ("2205", "Proveedores", 0, "#REF!"),
    ]
    for r in rows:
        ws.append(list(r))
    path = tmp_path / "bp.xlsx"
    wb.save(path)

    parsed = parse_document(path, "doc_bp")
    assert parsed.source.document_type == "TRIAL_BALANCE_XLSX"
    tb = {r.code: r for r in parsed.trial_balance_rows}
    assert {r.period for r in parsed.trial_balance_rows} == {"2024"}
    assert tb["110505"].is_leaf and tb["110510"].is_leaf
    assert not tb["1"].is_leaf and not tb["11"].is_leaf and not tb["1105"].is_leaf
    assert tb["110505"].display_value == 1000.0
    assert tb["110505"].cell_ref == "D5" or tb["110505"].cell_ref.startswith("D")
    assert tb["2205"].display_value is None
    content = parsed.source.pages[0].content
    for row in parsed.trial_balance_rows:
        assert row.quote in content
    assert any("ilegibles" in w for w in parsed.warnings)


def test_csv_semicolon_trial_balance(tmp_path):
    path = tmp_path / "balance_prueba_2023.csv"
    path.write_text(
        "Cuenta;Descripción;Saldo final\n1105;Caja;1.200,00\n4120;Ventas;5.000,00\n2205;Proveedores;800,00\n",
        encoding="cp1252",
    )
    parsed = parse_document(path, "doc_csv")
    assert parsed.source.file_format == "CSV"
    values = {r.code: r.display_value for r in parsed.trial_balance_rows}
    assert values == {"1105": 1200.0, "4120": 5000.0, "2205": 800.0}
    assert {r.period for r in parsed.trial_balance_rows} == {"2023"}
    assert parsed.trial_balance_rows[1].name == "Ventas"


def test_pdf_lines_have_columns_and_coordinates(tmp_path):
    import pymupdf as fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 80), "ESTADO DE SITUACIÓN FINANCIERA - cifras en miles de pesos", fontsize=9)
    page.insert_text((50, 100), "Efectivo y equivalentes", fontsize=9)
    page.insert_text((400, 100), "545.000", fontsize=9)
    page.insert_text((480, 100), "1.159.000", fontsize=9)
    path = tmp_path / "eeff_2025.pdf"
    pdf.save(path)
    pdf.close()

    parsed = parse_document(path, "doc_pdf")
    src = parsed.source
    assert src.document_type == "FINANCIAL_STATEMENTS_PDF"
    assert src.reported_units == "Miles de COP"
    lines = src.pages[0].content.splitlines()
    assert "Efectivo y equivalentes | 545.000 | 1.159.000" in lines
    assert len(src.pages[0].line_boxes) == len(lines)
    box = src.pages[0].line_boxes[1]
    assert box.x0 == pytest.approx(50, abs=1) and box.y1 > box.y0


def test_unsupported_extension(tmp_path):
    path = tmp_path / "memo.docx"
    path.write_bytes(b"x")
    with pytest.raises(UnsupportedDocumentError):
        parse_document(path, "doc_x")


def test_exported_demo_files_parse(demo_files):
    tb = parse_document(demo_files / "Balance_Prueba_Siigo_2023-2025.xlsx", "doc_bp")
    assert {r.period for r in tb.trial_balance_rows} == {"2023", "2024", "2025"}
    unreadable = [r for r in tb.trial_balance_rows if r.display_value is None]
    assert [r.code for r in unreadable] == ["2815"]
    cert = parse_document(demo_files / "Certificado_Existencia_Representacion_Legal_2025.pdf", "doc_cc")
    assert cert.source.document_type == "CHAMBER_OF_COMMERCE_CERT"
    eeff = parse_document(demo_files / "EEFF_2025_Alimentos_Conservas_Oriente.pdf", "doc_eeff")
    assert eeff.source.reported_units == "Miles de COP"


# ---------------------------------------------------------------------------
# Guardián de citas
# ---------------------------------------------------------------------------


def test_find_literal_tolerates_whitespace_and_case_but_returns_original():
    content = "Las pretensiones ascienden\na $850.000. Los asesores"
    literal = find_literal(content, "las PRETENSIONES ascienden a $850.000.")
    assert literal == "Las pretensiones ascienden\na $850.000."
    assert literal in content
    assert find_literal(content, "las pretensiones ascienden a $900.000.") is None
    assert find_literal(content, "abc") is None  # demasiado corta


def test_verify_quote_relocates_and_rejects_hallucinations(demo_files):
    from app.services.data_loader import load_demo_dossier

    docs = load_demo_dossier().documents
    ok = verify_quote(docs, "doc_eeff_2025", "Página 16", "Las pretensiones ascienden a $850.000.")
    assert ok.citation is not None and not ok.relocated
    assert ok.citation.cell_or_line_ref.startswith("Línea")
    moved = verify_quote(docs, "doc_eeff_2025", "Página 3", "Las pretensiones ascienden a $850.000.")
    assert moved.citation is not None and moved.relocated and moved.citation.page_or_sheet == "Página 16"
    fake = verify_quote(docs, "doc_eeff_2025", "Página 16", "Las pretensiones ascienden a $9.999.000.")
    assert fake.citation is None
