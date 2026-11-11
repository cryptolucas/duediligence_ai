"""Genera ``app/data/demo_deal_seed.json``: el caso demo "Alimentos y Conservas del Oriente S.A.S.".

Por qué un generador y no un JSON escrito a mano: cada ``exact_quote`` del expediente debe ser
una subcadena literal del texto de su documento. Construir documentos y citas desde la misma
tabla de datos garantiza esa trazabilidad y permite regenerar el caso de forma reproducible.

Empresa, personas, NIT y documentos son SINTÉTICOS (caso de demostración).

Uso:  python scripts/build_demo_seed.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.deal import DealDossier  # noqa: E402

OUTPUT = BACKEND_DIR / "app" / "data" / "demo_deal_seed.json"
PERIODS = ["2023", "2024", "2025"]
DEMO_BANNER = "DOCUMENTO SINTÉTICO DE DEMOSTRACIÓN — Catalejo Deal Desk"

# ---------------------------------------------------------------------------
# Identidad de la empresa
# ---------------------------------------------------------------------------

COMPANY = "Alimentos y Conservas del Oriente S.A.S."
NIT_BASE = "901234567"


def dian_check_digit(nit: str) -> int:
    """Dígito de verificación DIAN (módulo 11 con pesos primos)."""
    weights = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    total = sum(int(d) * w for d, w in zip(reversed(nit), weights))
    rem = total % 11
    return rem if rem in (0, 1) else 11 - rem


NIT = f"{NIT_BASE[:3]}.{NIT_BASE[3:6]}.{NIT_BASE[6:]}-{dian_check_digit(NIT_BASE)}"

# ---------------------------------------------------------------------------
# Balance de prueba (valores en MILES de COP, convención de signos del esquema)
# (código, nombre, categoría, {periodo: valor})
# ---------------------------------------------------------------------------

K = 1000  # miles -> COP

TB_ACCOUNTS: list[tuple[str, str, str, dict[str, int]]] = [
    # --- Activo ---
    ("1105", "Caja", "CASH", {"2023": 30_000, "2024": 38_000, "2025": 45_000}),
    ("1110", "Bancos", "CASH", {}),  # se calcula como cuadre del balance más abajo
    ("1305", "Clientes", "ACCOUNTS_RECEIVABLE", {"2023": 3_260_000, "2024": 3_780_000, "2025": 4_980_000}),
    ("1399", "Deterioro de deudores (CR)", "ACCOUNTS_RECEIVABLE", {"2023": -115_000, "2024": -150_000, "2025": -210_000}),
    ("1330", "Anticipos y avances", "OTHER_CURRENT_ASSETS", {"2023": 130_000, "2024": 150_000, "2025": 180_000}),
    ("1355", "Anticipo de impuestos y contribuciones", "OTHER_CURRENT_ASSETS", {"2023": 260_000, "2024": 290_000, "2025": 320_000}),
    ("1380", "Deudores varios", "OTHER_CURRENT_ASSETS", {"2023": 90_000, "2024": 160_000, "2025": 410_000}),
    ("1405", "Materias primas", "INVENTORY", {"2023": 1_050_000, "2024": 1_180_000, "2025": 1_350_000}),
    ("1430", "Productos terminados", "INVENTORY", {"2023": 1_620_000, "2024": 1_850_000, "2025": 2_240_000}),
    ("1455", "Materiales, repuestos y accesorios (envases)", "INVENTORY", {"2023": 330_000, "2024": 370_000, "2025": 410_000}),
    ("1504", "Terrenos", "PPE_AND_INTANGIBLES", {"2023": 1_200_000, "2024": 1_200_000, "2025": 1_200_000}),
    ("1516", "Construcciones y edificaciones", "PPE_AND_INTANGIBLES", {"2023": 2_800_000, "2024": 2_800_000, "2025": 2_800_000}),
    ("1520", "Maquinaria y equipo", "PPE_AND_INTANGIBLES", {"2023": 5_700_000, "2024": 6_350_000, "2025": 6_900_000}),
    ("1540", "Flota y equipo de transporte", "PPE_AND_INTANGIBLES", {"2023": 980_000, "2024": 980_000, "2025": 850_000}),
    ("1592", "Depreciación acumulada (CR)", "PPE_AND_INTANGIBLES", {"2023": -3_520_000, "2024": -4_100_000, "2025": -4_650_000}),
    ("1635", "Licencias", "PPE_AND_INTANGIBLES", {"2023": 120_000, "2024": 150_000, "2025": 180_000}),
    ("1910", "Valorizaciones de propiedades planta y equipo", "UNMAPPED", {"2023": 350_000}),
    # --- Pasivo ---
    ("21051001", "Pagarés entidades bancarias - corto plazo", "SHORT_TERM_DEBT", {"2023": 1_650_000, "2024": 1_800_000, "2025": 2_150_000}),
    ("21051002", "Pagarés entidades bancarias - largo plazo", "LONG_TERM_DEBT", {"2023": 2_700_000, "2024": 3_050_000, "2025": 3_400_000}),
    ("2120", "Compañías de financiamiento (leasing)", "LONG_TERM_DEBT", {"2023": 1_100_000, "2024": 1_250_000, "2025": 1_100_000}),
    ("2355", "Deudas con accionistas o socios", "LONG_TERM_DEBT", {"2023": 600_000, "2024": 600_000, "2025": 600_000}),
    ("2205", "Proveedores nacionales", "ACCOUNTS_PAYABLE", {"2023": 2_240_000, "2024": 2_520_000, "2025": 2_760_000}),
    ("2335", "Costos y gastos por pagar", "OTHER_CURRENT_LIABILITIES", {"2023": 430_000, "2024": 480_000, "2025": 540_000}),
    ("2365", "Retención en la fuente", "OTHER_CURRENT_LIABILITIES", {"2023": 80_000, "2024": 88_000, "2025": 95_000}),
    ("2404", "Impuesto de renta y complementarios por pagar", "OTHER_CURRENT_LIABILITIES", {}),  # = impuesto del año
    ("2505", "Salarios por pagar", "OTHER_CURRENT_LIABILITIES", {"2023": 95_000, "2024": 105_000, "2025": 120_000}),
    ("2510", "Cesantías consolidadas", "OTHER_CURRENT_LIABILITIES", {"2023": 210_000, "2024": 235_000, "2025": 260_000}),
    ("2805", "Anticipos y avances recibidos", "OTHER_CURRENT_LIABILITIES", {"2023": 70_000, "2024": 90_000, "2025": 120_000}),
    # --- Patrimonio (3605 se toma del ESF auditado; ver más abajo) ---
    ("3105", "Capital suscrito y pagado", "EQUITY", {"2023": 2_000_000, "2024": 2_000_000, "2025": 2_000_000}),
    ("3305", "Reserva legal", "EQUITY", {"2023": 1_000_000, "2024": 1_000_000, "2025": 1_000_000}),
    ("3705", "Utilidades acumuladas", "EQUITY", {}),  # roll-forward más abajo
    ("3805", "Superávit por valorizaciones", "UNMAPPED", {"2023": 350_000}),
    # --- Ingresos ---
    ("4120", "Industrias manufactureras", "REVENUE", {"2023": 23_410_000, "2024": 25_980_000, "2025": 28_790_000}),
    ("4175", "Devoluciones en ventas (DB)", "REVENUE", {"2023": -512_000, "2024": -585_000, "2025": -640_000}),
    ("4210", "Financieros", "NET_INTEREST", {"2023": -28_000, "2024": -35_000, "2025": -46_000}),
    ("4245", "Utilidad en venta de propiedades, planta y equipo", "OTHER_OP_INCOME_EXP", {"2025": 38_000}),
    ("4250", "Recuperaciones", "OTHER_OP_INCOME_EXP", {"2023": 35_000, "2024": 28_000, "2025": 41_000}),
    # --- Gastos ---
    ("5105", "Gastos de personal", "SGA", {"2023": 1_980_000, "2024": 2_240_000, "2025": 2_510_000}),
    ("5110", "Honorarios", "SGA", {"2023": 310_000, "2024": 365_000, "2025": 690_000}),
    ("5120", "Arrendamientos", "SGA", {"2023": 420_000, "2024": 456_000, "2025": 498_000}),
    ("5135", "Servicios", "SGA", {"2023": 380_000, "2024": 410_000, "2025": 445_000}),
    ("5160", "Depreciaciones", "DA", {"2023": 610_000, "2024": 655_000, "2025": 720_000}),
    ("5165", "Amortizaciones", "DA", {"2023": 40_000, "2024": 45_000, "2025": 52_000}),
    ("5195", "Diversos", "SGA", {"2023": 160_000, "2024": 175_000, "2025": 230_000}),
    ("5199", "Provisiones - deterioro de deudores", "SGA", {"2023": 45_000, "2024": 60_000, "2025": 140_000}),
    ("5205", "Gastos de personal - ventas", "SGA", {"2023": 820_000, "2024": 905_000, "2025": 1_010_000}),
    ("5235", "Servicios - ventas (fletes y acarreos)", "SGA", {"2023": 640_000, "2024": 715_000, "2025": 805_000}),
    ("5295", "Diversos - ventas (publicidad y degustaciones)", "SGA", {"2023": 210_000, "2024": 230_000, "2025": 252_000}),
    ("5305", "Financieros", "NET_INTEREST", {"2023": 640_000, "2024": 735_000, "2025": 790_000}),
    ("5315", "Gastos extraordinarios", "OTHER_OP_INCOME_EXP", {"2023": -22_000, "2024": -30_000, "2025": -64_000}),
    ("5405", "Impuesto de renta y complementarios", "TAXES", {}),  # 35 % de la utilidad antes de impuestos
    ("6120", "Costo de ventas - industrias manufactureras", "COGS", {"2023": 15_570_000, "2024": 17_150_000, "2025": 18_860_000}),
]

DIVIDENDS_PAID = {"2024": 300_000, "2025": 350_000}  # decretados sobre la utilidad del año anterior
RETAINED_EARNINGS_2023 = 1_240_000
TAX_RATE_PCT = 35

# Signo de presentación en el balance de prueba de Siigo: saldos crédito aparecen negativos.
CREDIT_NATURE_CATEGORIES = {
    "REVENUE",
    "OTHER_OP_INCOME_EXP",
    "ACCOUNTS_PAYABLE",
    "SHORT_TERM_DEBT",
    "OTHER_CURRENT_LIABILITIES",
    "LONG_TERM_DEBT",
    "EQUITY",
}
CREDIT_NATURE_UNMAPPED = {"3805"}

ASSETS = {"CASH", "ACCOUNTS_RECEIVABLE", "INVENTORY", "OTHER_CURRENT_ASSETS", "PPE_AND_INTANGIBLES"}
LIABS = {"ACCOUNTS_PAYABLE", "SHORT_TERM_DEBT", "OTHER_CURRENT_LIABILITIES", "LONG_TERM_DEBT"}


def acct(code: str) -> dict[str, int]:
    for c, _, _, vals in TB_ACCOUNTS:
        if c == code:
            return vals
    raise KeyError(code)


def cat_sum(category: str, period: str, exclude: tuple[str, ...] = ()) -> int:
    return sum(v.get(period, 0) for c, _, cat, v in TB_ACCOUNTS if cat == category and c not in exclude)


def codes_sum(codes: list[str], period: str) -> int:
    return sum(acct(c).get(period, 0) for c in codes)


# --- Completar impuestos, utilidades y cuadre de caja (aritmética del generador de datos sintéticos) ---
NET_INCOME: dict[str, int] = {}
for p in PERIODS:
    ebitda = (
        cat_sum("REVENUE", p) - cat_sum("COGS", p) - cat_sum("SGA", p) + cat_sum("OTHER_OP_INCOME_EXP", p)
    )
    ebt = ebitda - cat_sum("DA", p) - cat_sum("NET_INTEREST", p)
    tax = round(ebt * TAX_RATE_PCT / 100 / 1000) * 1000
    acct("5405")[p] = tax
    acct("2404")[p] = tax
    NET_INCOME[p] = ebt - tax

acct("3705")["2023"] = RETAINED_EARNINGS_2023
acct("3705")["2024"] = RETAINED_EARNINGS_2023 + NET_INCOME["2023"] - DIVIDENDS_PAID["2024"]
acct("3705")["2025"] = acct("3705")["2024"] + NET_INCOME["2024"] - DIVIDENDS_PAID["2025"]

for p in PERIODS:
    liabilities = sum(cat_sum(c, p) for c in LIABS)
    equity = cat_sum("EQUITY", p) + NET_INCOME[p]
    assets_ex_banks = sum(cat_sum(c, p) for c in ASSETS)  # 1110 aún vacío
    acct("1110")[p] = liabilities + equity - assets_ex_banks
    assert acct("1110")[p] > 0, f"Caja negativa en {p}"


# ---------------------------------------------------------------------------
# Formateo
# ---------------------------------------------------------------------------


def fmt_miles(v: int) -> str:
    """Formato de estados financieros: miles con punto, negativos entre paréntesis."""
    s = f"{abs(v):,}".replace(",", ".")
    return f"({s})" if v < 0 else s


def fmt_siigo(v_pesos: int) -> str:
    """Formato de celda exportada por Siigo: separador de miles '.' y decimales ','."""
    s = f"{abs(v_pesos):,}".replace(",", ".") + ",00"
    return f"-{s}" if v_pesos < 0 else s


def tb_display_value(code: str, category: str, value_thousands: int) -> int:
    credit = category in CREDIT_NATURE_CATEGORIES or code in CREDIT_NATURE_UNMAPPED
    sign = -1 if credit else 1
    return sign * value_thousands * K


# ---------------------------------------------------------------------------
# Documentos y citas
# ---------------------------------------------------------------------------

DOCS: dict[str, dict] = {}
CITATIONS: dict[str, dict] = {}


def add_doc(doc_id: str, name: str, doc_type: str, fmt: str, description: str, units: str) -> None:
    DOCS[doc_id] = {
        "document_id": doc_id,
        "document_name": name,
        "document_type": doc_type,
        "file_format": fmt,
        "description": description,
        "reported_units": units,
        "pages": [],
    }


def add_page(doc_id: str, page: str, lines: list[str]) -> None:
    DOCS[doc_id]["pages"].append({"page_or_sheet": page, "content": "\n".join(lines)})


def page_content(doc_id: str, page: str) -> str:
    for pg in DOCS[doc_id]["pages"]:
        if pg["page_or_sheet"] == page:
            return pg["content"]
    raise KeyError((doc_id, page))


def cite(cid: str, doc_id: str, page: str, quote: str, ref: str | None, confidence: float) -> dict:
    content = page_content(doc_id, page)
    if quote not in content:
        raise ValueError(f"[{cid}] la cita no es literal en {doc_id}/{page}: {quote!r}")
    if ref is None:
        line_no = content[: content.index(quote)].count("\n") + 1
        ref = f"Línea {line_no}"
    citation = {
        "citation_id": cid,
        "document_id": doc_id,
        "document_name": DOCS[doc_id]["document_name"],
        "page_or_sheet": page,
        "cell_or_line_ref": ref,
        "exact_quote": quote,
        "confidence": confidence,
    }
    if cid in CITATIONS and CITATIONS[cid] != citation:
        raise ValueError(f"Cita {cid} redefinida con contenido distinto")
    CITATIONS[cid] = citation
    return citation


# --- 1. Balance de prueba Siigo (COP plenos) --------------------------------

DOC_BP = "doc_bp_siigo"
add_doc(
    DOC_BP,
    "Balance_Prueba_Siigo_2023-2025.xlsx",
    "TRIAL_BALANCE_XLSX",
    "XLSX",
    "Balances de prueba anuales exportados de Siigo Nube (pre-cierre), una hoja por año.",
    "COP",
)

TB_FIRST_ROW = 7
TB_ROW_INDEX: dict[tuple[str, str], int] = {}
for p in PERIODS:
    lines = [
        f"{DEMO_BANNER}",
        f"Fila 2 | {COMPANY.upper()} - NIT {NIT}",
        f"Fila 3 | BALANCE DE PRUEBA POR CUENTA - 01/01/{p} A 31/12/{p} - Siigo Nube",
        "Fila 4 | Saldos crédito presentados con signo negativo",
        "Fila 6 | Código | Nombre cuenta | Saldo final",
    ]
    row = TB_FIRST_ROW
    for code, name, category, vals in sorted(TB_ACCOUNTS, key=lambda a: a[0]):
        if p not in vals:
            continue
        display = tb_display_value(code, category, vals[p])
        lines.append(f"Fila {row} | {code} | {name} | {fmt_siigo(display)}")
        TB_ROW_INDEX[(p, code)] = row
        row += 1
    if p == "2025":
        lines.append(f"Fila {row} | 2815 | Ingresos recibidos para terceros | #¡REF!")
        TB_ROW_INDEX[(p, "2815")] = row
        row += 1
    lines.append(f"Fila {row + 1} | TOTALES | Sumas iguales | 0,00")
    add_page(DOC_BP, f"BP_{p}", lines)


def tb_quote(p: str, code: str) -> tuple[str, str]:
    for c, name, category, vals in TB_ACCOUNTS:
        if c == code:
            return f"{code} | {name} | {fmt_siigo(tb_display_value(code, category, vals[p]))}", f"C{TB_ROW_INDEX[(p, code)]}"
    raise KeyError(code)


def tb_cite(p: str, code: str) -> dict:
    quote, ref = tb_quote(p, code)
    return cite(f"cit_bp{p[2:]}_{code}", DOC_BP, f"BP_{p}", quote, ref, 0.99)


# --- 2. Estados financieros auditados (miles de COP) ------------------------


def esf_lines(cur: str, prev: str) -> list[str]:
    def row(label: str, a: int, b: int) -> str:
        return f"{label} | {fmt_miles(a)} | {fmt_miles(b)}"

    def g(codes: list[str], p: str) -> int:
        return codes_sum(codes, p)

    ca = ["1105", "1110", "1305", "1399", "1330", "1380", "1355", "1405", "1430", "1455"]
    ppe = ["1504", "1516", "1520", "1540", "1592"]
    cl = ["21051001", "2205", "2335", "2365", "2805", "2404", "2505", "2510"]
    ncl = ["21051002", "2120", "2355"]
    out = [
        "ESTADO DE SITUACIÓN FINANCIERA AL 31 DE DICIEMBRE",
        f"(Cifras expresadas en miles de pesos colombianos) | {cur} | {prev}",
        row("Efectivo y equivalentes al efectivo (Nota 5)", g(["1105", "1110"], cur), g(["1105", "1110"], prev)),
        row("Deudores comerciales, neto (Nota 7)", g(["1305", "1399"], cur), g(["1305", "1399"], prev)),
        row("Otras cuentas por cobrar (Nota 7)", g(["1330", "1380"], cur), g(["1330", "1380"], prev)),
        row("Activos por impuestos corrientes", g(["1355"], cur), g(["1355"], prev)),
        row("Inventarios (Nota 8)", g(["1405", "1430", "1455"], cur), g(["1405", "1430", "1455"], prev)),
        row("Total activo corriente", g(ca, cur), g(ca, prev)),
        row("Propiedades, planta y equipo, neto (Nota 10)", g(ppe, cur), g(ppe, prev)),
        row("Activos intangibles", g(["1635"], cur), g(["1635"], prev)),
        row("Total activo no corriente", g(ppe + ["1635"], cur), g(ppe + ["1635"], prev)),
        row("TOTAL ACTIVO", g(ca + ppe + ["1635"], cur), g(ca + ppe + ["1635"], prev)),
        row("Obligaciones financieras corrientes (Nota 12)", g(["21051001"], cur), g(["21051001"], prev)),
        row("Proveedores", g(["2205"], cur), g(["2205"], prev)),
        row("Cuentas por pagar y otros pasivos", g(["2335", "2365", "2805"], cur), g(["2335", "2365", "2805"], prev)),
        row("Pasivos por impuestos corrientes", g(["2404"], cur), g(["2404"], prev)),
        row("Beneficios a empleados", g(["2505", "2510"], cur), g(["2505", "2510"], prev)),
        row("Total pasivo corriente", g(cl, cur), g(cl, prev)),
        row("Obligaciones financieras no corrientes (Nota 12)", g(["21051002", "2120"], cur), g(["21051002", "2120"], prev)),
        row("Cuentas por pagar a accionistas (Nota 24)", g(["2355"], cur), g(["2355"], prev)),
        row("Total pasivo no corriente", g(ncl, cur), g(ncl, prev)),
        row("TOTAL PASIVO", g(cl + ncl, cur), g(cl + ncl, prev)),
        row("Capital suscrito y pagado", g(["3105"], cur), g(["3105"], prev)),
        row("Reservas", g(["3305"], cur), g(["3305"], prev)),
        row("Resultados acumulados", g(["3705"], cur), g(["3705"], prev)),
        row("Resultado del ejercicio", NET_INCOME[cur], NET_INCOME[prev]),
        row(
            "TOTAL PATRIMONIO",
            g(["3105", "3305", "3705"], cur) + NET_INCOME[cur],
            g(["3105", "3305", "3705"], prev) + NET_INCOME[prev],
        ),
        row(
            "TOTAL PASIVO Y PATRIMONIO",
            g(cl + ncl + ["3105", "3305", "3705"], cur) + NET_INCOME[cur],
            g(cl + ncl + ["3105", "3305", "3705"], prev) + NET_INCOME[prev],
        ),
    ]
    return out


def eri_lines(cur: str, prev: str) -> list[str]:
    def row(label: str, a: int, b: int) -> str:
        return f"{label} | {fmt_miles(a)} | {fmt_miles(b)}"

    def rev(p: str) -> int:
        return cat_sum("REVENUE", p)

    def admin(p: str) -> int:
        return codes_sum(["5105", "5110", "5120", "5135", "5160", "5165", "5195", "5199"], p)

    def sales(p: str) -> int:
        return codes_sum(["5205", "5235", "5295"], p)

    def other_inc(p: str) -> int:
        return codes_sum(["4245", "4250"], p)

    def op(p: str) -> int:
        return rev(p) - acct("6120")[p] - admin(p) - sales(p) + other_inc(p) + acct("5315")[p]

    def ebt(p: str) -> int:
        return op(p) - acct("5305")[p] - acct("4210")[p]

    return [
        "ESTADO DE RESULTADOS INTEGRAL POR LOS AÑOS TERMINADOS EL 31 DE DICIEMBRE",
        f"(Cifras expresadas en miles de pesos colombianos) | {cur} | {prev}",
        row("Ingresos de actividades ordinarias (Nota 17)", rev(cur), rev(prev)),
        row("Costo de ventas", -acct("6120")[cur], -acct("6120")[prev]),
        row("Utilidad bruta", rev(cur) - acct("6120")[cur], rev(prev) - acct("6120")[prev]),
        row("Gastos de administración (Nota 18)", -admin(cur), -admin(prev)),
        row("Gastos de ventas", -sales(cur), -sales(prev)),
        row("Otros ingresos (Nota 20)", other_inc(cur), other_inc(prev)),
        row("Otros gastos (Nota 19)", acct("5315")[cur], acct("5315")[prev]),
        row("Resultado operacional", op(cur), op(prev)),
        row("Ingresos financieros", -acct("4210")[cur], -acct("4210")[prev]),
        row("Gastos financieros (Nota 12)", -acct("5305")[cur], -acct("5305")[prev]),
        row("Utilidad antes de impuestos", ebt(cur), ebt(prev)),
        row("Impuesto de renta (Nota 23)", -acct("5405")[cur], -acct("5405")[prev]),
        row("RESULTADO DEL EJERCICIO", NET_INCOME[cur], NET_INCOME[prev]),
    ]


DOC_EEFF25 = "doc_eeff_2025"
add_doc(
    DOC_EEFF25,
    "EEFF_2025_Alimentos_Conservas_Oriente.pdf",
    "FINANCIAL_STATEMENTS_PDF",
    "PDF",
    "Estados financieros comparativos 2025-2024 bajo NIIF para PYMES (Grupo 2) con notas y dictamen del revisor fiscal.",
    "Miles de COP",
)
add_page(
    DOC_EEFF25,
    "Página 2",
    [
        DEMO_BANNER,
        "DICTAMEN DEL REVISOR FISCAL",
        "En mi opinión, los estados financieros adjuntos presentan razonablemente, en todos los aspectos materiales, la situación financiera de la Compañía al 31 de diciembre de 2025.",
        "Párrafo de énfasis: Sin modificar mi opinión, llamo la atención sobre la Nota 22, en la que se describe un proceso laboral ordinario en contra de la Compañía cuyo desenlace no puede determinarse a la fecha; la administración no ha reconocido provisión alguna.",
        "Firma: Revisor Fiscal T.P. (sintético) — Rionegro, 6 de marzo de 2026.",
    ],
)
add_page(DOC_EEFF25, "Página 3", [DEMO_BANNER, *esf_lines("2025", "2024")])
add_page(DOC_EEFF25, "Página 4", [DEMO_BANNER, *eri_lines("2025", "2024")])
add_page(
    DOC_EEFF25,
    "Página 9",
    [
        DEMO_BANNER,
        "NOTA 7 - DEUDORES COMERCIALES Y OTRAS CUENTAS POR COBRAR",
        "Antigüedad de la cartera de clientes (miles de COP) | 2025 | 2024",
        "Corriente (0-30 días) | 3.050.000 | 2.690.000",
        "Vencida 31-90 días | 1.090.000 | 760.000",
        "Vencida 91-180 días | 520.000 | 210.000",
        "Vencida más de 180 días | 320.000 | 120.000",
        "Total clientes | 4.980.000 | 3.780.000",
        "La cartera vencida a más de 90 días incluye $620.000 a cargo de Supermercados La Económica del Caribe S.A.S., sociedad admitida a proceso de reorganización empresarial (Ley 1116 de 2006) en septiembre de 2025.",
        "La Compañía registró deterioro de cartera por $140.000 en 2025 (2024: $60.000) aplicando el modelo de pérdida incurrida.",
        "Deudores varios incluye préstamos a accionistas por $410.000 (2024: $160.000), sin plazo de pago ni intereses pactados.",
    ],
)
add_page(
    DOC_EEFF25,
    "Página 12",
    [
        DEMO_BANNER,
        "NOTA 12 - OBLIGACIONES FINANCIERAS",
        "Las obligaciones con entidades bancarias corresponden a pagarés en pesos a tasa IBR + 6,5 puntos, con vencimientos entre 2026 y 2030.",
        "Los créditos están garantizados con hipoteca abierta de primer grado sobre la planta de producción ubicada en Rionegro, Antioquia.",
        "Los contratos de crédito establecen que la relación Deuda financiera / EBITDA no debe superar 2,5 veces, medida al cierre de cada año con base en los estados financieros dictaminados.",
        "El incumplimiento de esta condición faculta al banco para declarar el plazo vencido de la totalidad de las obligaciones.",
        "Los contratos de leasing financiero corresponden a dos líneas de esterilización (autoclaves) con opción de compra del 1 %.",
    ],
)
add_page(
    DOC_EEFF25,
    "Página 15",
    [
        DEMO_BANNER,
        "NOTA 19 - GASTOS DIVERSOS Y OTROS GASTOS",
        "El rubro de gastos diversos de administración (cuenta 5195) por $230.000 (2024: $175.000) incluye $74.000 correspondientes a cuotas de club social y gastos de vehículos asignados a accionistas.",
        "Los gastos extraordinarios por $64.000 corresponden a multas y sanciones, impuestos asumidos y donaciones.",
    ],
)
add_page(
    DOC_EEFF25,
    "Página 16",
    [
        DEMO_BANNER,
        "NOTA 22 - PROVISIONES Y PASIVOS CONTINGENTES",
        "Proceso laboral ordinario promovido por once (11) extrabajadores de la planta de Rionegro que reclaman el reconocimiento de contrato realidad con la Compañía y no con la cooperativa de trabajo asociado que los vinculó entre 2017 y 2021.",
        "Las pretensiones ascienden a $850.000. Los asesores legales califican la probabilidad de pérdida como posible; en consecuencia no se ha reconocido provisión.",
        "Durante 2025 la Compañía pagó honorarios de defensa a la firma de abogados externa por $280.000, registrados en el rubro de honorarios (cuenta 5110).",
    ],
)
add_page(
    DOC_EEFF25,
    "Página 17",
    [
        DEMO_BANNER,
        "NOTA 23 - IMPUESTO A LAS GANANCIAS",
        "La tarifa nominal de impuesto de renta aplicable es del 35 %.",
        "En noviembre de 2025 la DIAN notificó requerimiento especial sobre la declaración de renta del año gravable 2022, proponiendo el rechazo de costos por $310.000 más sanción por inexactitud.",
        "La administración, con apoyo de sus asesores tributarios, considera que la probabilidad de un fallo desfavorable es posible y no ha registrado provisión.",
    ],
)
add_page(
    DOC_EEFF25,
    "Página 18",
    [
        DEMO_BANNER,
        "NOTA 24 - PARTES RELACIONADAS",
        "Arrendamiento de la bodega de producto terminado ubicada en Rionegro, de propiedad del accionista Jorge Enrique Ramírez Gómez: $498.000 (2024: $456.000).",
        "Remuneración pagada a familiares cercanos de accionistas sin cargo operativo en la Compañía (cónyuge e hija del accionista mayoritario): $312.000 (2024: $288.000).",
        "Remuneración del Gerente General (personal clave de la gerencia): $204.000 (2024: $192.000).",
        "Préstamos otorgados por la Compañía a accionistas: $410.000 (2024: $160.000). Préstamos recibidos de accionistas: $600.000 (2024: $600.000), sin fecha de vencimiento.",
    ],
)

DOC_EEFF24 = "doc_eeff_2024"
add_doc(
    DOC_EEFF24,
    "EEFF_2024_Alimentos_Conservas_Oriente.pdf",
    "FINANCIAL_STATEMENTS_PDF",
    "PDF",
    "Estados financieros comparativos 2024-2023 bajo NIIF para PYMES (Grupo 2) con notas.",
    "Miles de COP",
)
add_page(DOC_EEFF24, "Página 3", [DEMO_BANNER, *esf_lines("2024", "2023")])
add_page(
    DOC_EEFF24,
    "Página 17",
    [
        DEMO_BANNER,
        "NOTA 24 - PARTES RELACIONADAS",
        "Arrendamiento de la bodega de producto terminado ubicada en Rionegro, de propiedad del accionista Jorge Enrique Ramírez Gómez: $456.000 (2023: $420.000).",
        "Remuneración pagada a familiares cercanos de accionistas sin cargo operativo en la Compañía (cónyuge e hija del accionista mayoritario): $288.000 (2023: $265.000).",
    ],
)

# --- 3. Avalúo de canon de arrendamiento ------------------------------------

DOC_AVALUO = "doc_avaluo_bodega"
add_doc(
    DOC_AVALUO,
    "Avaluo_Canon_Arrendamiento_Bodega_Rionegro.pdf",
    "APPRAISAL",
    "PDF",
    "Estudio de canon de arrendamiento de mercado de la bodega arrendada al accionista (avaluador sintético).",
    "COP",
)
add_page(
    DOC_AVALUO,
    "Página 3",
    [
        DEMO_BANNER,
        "5. CONCLUSIÓN DEL CANON DE MERCADO — Bodega de 2.400 m² en zona industrial de Rionegro",
        "Comparables utilizados: 6 bodegas de 1.800 a 3.000 m² en corredor Rionegro - Marinilla, ofertas y contratos 2023-2025.",
        "Para 2023 el canon pactado ($420.000.000) supera el canon de mercado estimado ($276.000.000) en $144.000.000.",
        "Para 2024 el canon pactado ($456.000.000) supera el canon de mercado estimado ($300.000.000) en $156.000.000.",
        "Para 2025 el canon pactado ($498.000.000) supera el canon de mercado estimado ($330.000.000) en $168.000.000.",
    ],
)

# --- 4. Certificado de Cámara de Comercio -----------------------------------

DOC_CCIO = "doc_camara_comercio"
add_doc(
    DOC_CCIO,
    "Certificado_Existencia_Representacion_Legal_2025.pdf",
    "CHAMBER_OF_COMMERCE_CERT",
    "PDF",
    "Certificado de existencia y representación legal expedido en diciembre de 2025 (sintético).",
    "COP",
)
add_page(
    DOC_CCIO,
    "Página 1",
    [
        DEMO_BANNER,
        "CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL",
        f"Razón social: {COMPANY.upper()}",
        f"NIT: {NIT}",
        "Domicilio principal: Rionegro (Antioquia)",
        "Constitución: Escritura Pública No. 812 del 14 de marzo de 2006 como sociedad limitada; transformada en sociedad por acciones simplificada mediante Acta No. 21 de Asamblea del 2 de julio de 2012.",
        "Actividad principal: Código CIIU 1020 - Procesamiento y conservación de frutas, legumbres, hortalizas y tubérculos",
        "Actividad secundaria: Código CIIU 4631 - Comercio al por mayor de productos alimenticios",
        "Capital autorizado: $3.000.000.000 | Capital suscrito: $2.000.000.000 | Capital pagado: $2.000.000.000",
        "Número de acciones suscritas: 2.000.000 | Valor nominal: $1.000",
    ],
)
add_page(
    DOC_CCIO,
    "Página 2",
    [
        DEMO_BANNER,
        "REPRESENTACIÓN LEGAL",
        "Gerente (representante legal principal): JORGE ENRIQUE RAMÍREZ GÓMEZ",
        "Suplente del Gerente: MARÍA FERNANDA RAMÍREZ OSPINA",
        "FACULTADES DEL REPRESENTANTE LEGAL: El Gerente requerirá autorización previa de la Asamblea General de Accionistas para celebrar actos o contratos cuya cuantía exceda de quinientos (500) salarios mínimos mensuales legales vigentes.",
        "Igualmente requerirá autorización de la Asamblea para enajenar o gravar a cualquier título los activos fijos de la sociedad.",
        "Le está prohibido constituir a la sociedad como garante de obligaciones de terceros o de sus accionistas sin autorización expresa de la Asamblea.",
        "REVISOR FISCAL: inscrito (persona natural, sintético).",
    ],
)

# --- 5. Teaser ---------------------------------------------------------------

DOC_TEASER = "doc_teaser"
add_doc(
    DOC_TEASER,
    "Teaser_Proyecto_Conserva.pdf",
    "TEASER",
    "PDF",
    "Teaser de 2 páginas preparado por el asesor de la compañía para inversionistas (Proyecto Conserva).",
    "COP millones",
)
add_page(
    DOC_TEASER,
    "Página 1",
    [
        DEMO_BANNER,
        "PROYECTO CONSERVA — Oportunidad de inversión en procesador de frutas y hortalizas del Oriente Antioqueño",
        "Más de 18 años en el mercado, con planta certificada BPM e INVIMA en Rionegro y portafolio de 64 referencias (conservas, mermeladas, salsas y pulpas).",
        "Crecimiento anual de ventas superior al 15 % en los últimos tres años.",
        "EBITDA ajustado 2025: COP 3.900 millones.",
        "Los tres principales clientes (grandes superficies nacionales) representan el 48 % de las ventas.",
        "Capacidad instalada utilizada: 62 %, lo que permite crecer sin CAPEX relevante.",
    ],
)
add_page(
    DOC_TEASER,
    "Página 2",
    [
        DEMO_BANNER,
        "ESTRUCTURA ACCIONARIA Y TRANSACCIÓN PROPUESTA",
        "Composición accionaria: Jorge Enrique Ramírez Gómez 60 %, Gloria Inés Ospina de Ramírez 20 %, María Fernanda Ramírez Ospina 10 %, Andrés Felipe Ramírez Ospina 10 %.",
        "Se busca un socio financiero para adquirir hasta el 40 % de las acciones mediante una combinación de compra secundaria y capitalización primaria.",
        "Los recursos primarios se destinarían a una línea de pulpas congeladas para exportación.",
    ],
)

# ---------------------------------------------------------------------------
# Cuentas mapeadas
# ---------------------------------------------------------------------------

RATIONALE_BY_CODE = {
    "1105": "PUC 1105 Caja: efectivo disponible -> CASH.",
    "1110": "PUC 1110 Bancos: saldos en cuentas bancarias -> CASH.",
    "1305": "PUC 1305 Clientes: cartera comercial bruta -> ACCOUNTS_RECEIVABLE.",
    "1399": "PUC 1399 Deterioro (provisión) de deudores: cuenta correctora de naturaleza crédito, se resta de ACCOUNTS_RECEIVABLE.",
    "1330": "PUC 1330 Anticipos y avances a proveedores: activo corriente no comercial -> OTHER_CURRENT_ASSETS.",
    "1355": "PUC 1355 Anticipo de impuestos (retenciones y autorretenciones): activo por impuesto corriente -> OTHER_CURRENT_ASSETS.",
    "1380": "PUC 1380 Deudores varios: incluye préstamos a accionistas (Nota 7). No es cartera comercial -> OTHER_CURRENT_ASSETS; se excluye del capital de trabajo operativo.",
    "1405": "PUC 1405 Materias primas (fruta, hortaliza, azúcar) -> INVENTORY.",
    "1430": "PUC 1430 Productos terminados -> INVENTORY.",
    "1455": "PUC 1455 Materiales y repuestos (envases de vidrio y hojalata) -> INVENTORY.",
    "1504": "PUC 1504 Terrenos -> PPE_AND_INTANGIBLES.",
    "1516": "PUC 1516 Construcciones y edificaciones (planta Rionegro) -> PPE_AND_INTANGIBLES.",
    "1520": "PUC 1520 Maquinaria y equipo de proceso -> PPE_AND_INTANGIBLES.",
    "1540": "PUC 1540 Flota y equipo de transporte -> PPE_AND_INTANGIBLES.",
    "1592": "PUC 1592 Depreciación acumulada: cuenta correctora crédito, se resta de PPE_AND_INTANGIBLES.",
    "1635": "PUC 1635 Licencias de software: intangible -> PPE_AND_INTANGIBLES.",
    "1910": "PUC 1910 Valorizaciones (Decreto 2649/93): no se reconocen bajo NIIF para PYMES; no aparece en el ESF auditado 2023. Se deja UNMAPPED y se excluye de los cálculos.",
    "21051001": "Auxiliar Siigo 21051001 Pagarés bancarios porción corriente: deuda financiera con costo -> SHORT_TERM_DEBT. Saldo crédito exportado negativo; se invierte el signo.",
    "21051002": "Auxiliar Siigo 21051002 Pagarés bancarios porción no corriente -> LONG_TERM_DEBT. Saldo crédito exportado negativo; se invierte el signo.",
    "2120": "PUC 2120 Compañías de financiamiento (leasing financiero de autoclaves, Nota 12) -> LONG_TERM_DEBT. Se invierte el signo del saldo crédito.",
    "2355": "PUC 2355 Deudas con accionistas: préstamos de socios sin vencimiento (Nota 24). Se trata como deuda (debt-like) de forma conservadora -> LONG_TERM_DEBT.",
    "2205": "PUC 2205 Proveedores nacionales -> ACCOUNTS_PAYABLE. Se invierte el signo del saldo crédito.",
    "2335": "PUC 2335 Costos y gastos por pagar -> OTHER_CURRENT_LIABILITIES.",
    "2365": "PUC 2365 Retención en la fuente por pagar -> OTHER_CURRENT_LIABILITIES.",
    "2404": "PUC 2404 Impuesto de renta por pagar -> OTHER_CURRENT_LIABILITIES.",
    "2505": "PUC 2505 Salarios por pagar -> OTHER_CURRENT_LIABILITIES.",
    "2510": "PUC 2510 Cesantías consolidadas -> OTHER_CURRENT_LIABILITIES.",
    "2805": "PUC 2805 Anticipos recibidos de clientes -> OTHER_CURRENT_LIABILITIES.",
    "3105": "PUC 3105 Capital suscrito y pagado -> EQUITY.",
    "3305": "PUC 3305 Reserva legal -> EQUITY.",
    "3705": "PUC 3705 Utilidades acumuladas -> EQUITY.",
    "3805": "PUC 3805 Superávit por valorizaciones: contrapartida de 1910, no reconocido bajo NIIF. UNMAPPED, excluido de los cálculos.",
    "4120": "PUC 4120 Ingresos operacionales - industrias manufactureras -> REVENUE. Saldo crédito exportado negativo; se invierte el signo.",
    "4175": "PUC 4175 Devoluciones, rebajas y descuentos en ventas: cuenta débito que reduce ingresos -> REVENUE con signo negativo.",
    "4210": "PUC 4210 Ingresos financieros: se netea contra gastos financieros -> NET_INTEREST con signo negativo.",
    "4245": "PUC 4245 Utilidad en venta de PPE: ingreso operativo no recurrente -> OTHER_OP_INCOME_EXP (positivo). Candidato a ajuste de normalización.",
    "4250": "PUC 4250 Recuperaciones (reintegro de costos y deterioros) -> OTHER_OP_INCOME_EXP (positivo).",
    "5105": "PUC 5105 Gastos de personal de administración -> SGA. Incluye remuneración de familiares sin cargo operativo (Nota 24).",
    "5110": "PUC 5110 Honorarios -> SGA. Incluye honorarios de defensa del proceso laboral (Nota 22).",
    "5120": "PUC 5120 Arrendamientos -> SGA. Incluye arriendo de bodega a accionista (Nota 24).",
    "5135": "PUC 5135 Servicios (energía, vigilancia, aseo) -> SGA.",
    "5160": "PUC 5160 Depreciaciones: la política contable registra toda la depreciación en el gasto (no se absorbe en el costo) -> DA.",
    "5165": "PUC 5165 Amortizaciones de intangibles -> DA.",
    "5195": "PUC 5195 Gastos diversos -> SGA. Incluye gastos personales de accionistas (Nota 19).",
    "5199": "PUC 5199 Provisiones (deterioro de deudores): gasto operativo recurrente asociado a la cartera -> SGA.",
    "5205": "PUC 5205 Gastos de personal de ventas -> SGA.",
    "5235": "PUC 5235 Servicios de ventas (fletes y acarreos a clientes) -> SGA.",
    "5295": "PUC 5295 Diversos de ventas (publicidad, degustaciones) -> SGA.",
    "5305": "PUC 5305 Gastos financieros (intereses, comisiones bancarias) -> NET_INTEREST.",
    "5315": "PUC 5315 Gastos extraordinarios: gasto no operativo recurrente pequeño -> OTHER_OP_INCOME_EXP (negativo).",
    "5405": "PUC 5405 Impuesto de renta y complementarios -> TAXES.",
    "6120": "PUC 6120 Costo de ventas - industrias manufactureras (sin depreciación, ver 5160) -> COGS.",
}

mapped_accounts: list[dict] = []
for p in PERIODS:
    for code, name, category, vals in sorted(TB_ACCOUNTS, key=lambda a: a[0]):
        if p not in vals:
            continue
        mapped_accounts.append(
            {
                "raw_account_code": code,
                "raw_account_name": name,
                "standard_category": category,
                "period": p,
                "raw_value_cop": float(vals[p] * K),
                "mapping_rationale": RATIONALE_BY_CODE[code],
                "citation": tb_cite(p, code),
            }
        )

# Resultado del ejercicio: el balance de prueba es pre-cierre; se toma del ESF dictaminado.
NI_SOURCES = {"2025": (DOC_EEFF25, 0), "2024": (DOC_EEFF25, 1), "2023": (DOC_EEFF24, 1)}
for p, (doc_id, col) in NI_SOURCES.items():
    cur = "2025" if doc_id == DOC_EEFF25 else "2024"
    prev = "2024" if doc_id == DOC_EEFF25 else "2023"
    quote = f"Resultado del ejercicio | {fmt_miles(NET_INCOME[cur])} | {fmt_miles(NET_INCOME[prev])}"
    c = cite(f"cit_{doc_id}_ni_{p}", doc_id, "Página 3", quote, f"Resultado del ejercicio, columna {p}", 0.97)
    mapped_accounts.append(
        {
            "raw_account_code": "3605",
            "raw_account_name": "Resultado del ejercicio",
            "standard_category": "EQUITY",
            "period": p,
            "raw_value_cop": float(NET_INCOME[p] * K),
            "mapping_rationale": (
                "El balance de prueba de Siigo es pre-cierre (no incluye 3605). El resultado del ejercicio se toma "
                f"del Estado de Situación Financiera dictaminado, columna {p}, expresado en miles de COP (x1.000)."
            ),
            "citation": c,
        }
    )

# ---------------------------------------------------------------------------
# Ajustes al EBITDA (propuestos por el agente financiero; montos citados literalmente)
# ---------------------------------------------------------------------------


def note_cite(cid: str, doc_id: str, page: str, quote: str, conf: float = 0.95) -> dict:
    return cite(cid, doc_id, page, quote, None, conf)


cit_fam_25 = note_cite("cit_n24_familiares_2025", DOC_EEFF25, "Página 18", "(cónyuge e hija del accionista mayoritario): $312.000 (2024: $288.000)")
cit_fam_23 = note_cite("cit_n24_familiares_2023", DOC_EEFF24, "Página 17", "(cónyuge e hija del accionista mayoritario): $288.000 (2023: $265.000)")
cit_rent_25 = note_cite("cit_avaluo_2025", DOC_AVALUO, "Página 3", "Para 2025 el canon pactado ($498.000.000) supera el canon de mercado estimado ($330.000.000) en $168.000.000.", 0.93)
cit_rent_24 = note_cite("cit_avaluo_2024", DOC_AVALUO, "Página 3", "Para 2024 el canon pactado ($456.000.000) supera el canon de mercado estimado ($300.000.000) en $156.000.000.", 0.93)
cit_rent_23 = note_cite("cit_avaluo_2023", DOC_AVALUO, "Página 3", "Para 2023 el canon pactado ($420.000.000) supera el canon de mercado estimado ($276.000.000) en $144.000.000.", 0.93)
cit_legal_fees = note_cite("cit_n22_honorarios", DOC_EEFF25, "Página 16", "pagó honorarios de defensa a la firma de abogados externa por $280.000, registrados en el rubro de honorarios (cuenta 5110)")
cit_personal = note_cite("cit_n19_personales", DOC_EEFF25, "Página 15", "incluye $74.000 correspondientes a cuotas de club social y gastos de vehículos asignados a accionistas")
cit_gain_ppe = CITATIONS["cit_bp25_4245"]

ADJ = []


def add_adj(adj_id, title, category, period, amount_thousands, rationale, citation, status="ACCEPTED"):
    ADJ.append(
        {
            "id": adj_id,
            "title": title,
            "category": category,
            "period": period,
            "amount_cop": float(amount_thousands * K),
            "rationale": rationale,
            "status": status,
            "citation": citation,
            "origin": "AI_PROPOSED",
        }
    )


FAM_RATIONALE = (
    "La Nota 24 revela salarios pagados al cónyuge y a la hija del accionista mayoritario sin cargo operativo. "
    "Un comprador no asumiría este costo: se suma de vuelta al EBITDA. Monto tomado literal de la nota (miles de COP)."
)
RENT_RATIONALE = (
    "La bodega es propiedad del accionista mayoritario. Solo se normaliza el exceso del canon pactado sobre el canon "
    "de mercado, cifra que el avalúo independiente reporta literalmente; el canon de mercado sigue siendo un costo operativo."
)
add_adj("adj_2023_fam", "Salarios de familiares sin cargo operativo (cónyuge e hija)", "OWNER_COMPENSATION", "2023", 265_000, FAM_RATIONALE, cit_fam_23)
add_adj("adj_2023_rent", "Exceso de arriendo de bodega pagado al socio sobre canon de mercado", "RELATED_PARTY_RENT", "2023", 144_000, RENT_RATIONALE, cit_rent_23)
add_adj("adj_2024_fam", "Salarios de familiares sin cargo operativo (cónyuge e hija)", "OWNER_COMPENSATION", "2024", 288_000, FAM_RATIONALE, cit_fam_25)
add_adj("adj_2024_rent", "Exceso de arriendo de bodega pagado al socio sobre canon de mercado", "RELATED_PARTY_RENT", "2024", 156_000, RENT_RATIONALE, cit_rent_24)
add_adj("adj_2025_fam", "Salarios de familiares sin cargo operativo (cónyuge e hija)", "OWNER_COMPENSATION", "2025", 312_000, FAM_RATIONALE, cit_fam_25)
add_adj("adj_2025_rent", "Exceso de arriendo de bodega pagado al socio sobre canon de mercado", "RELATED_PARTY_RENT", "2025", 168_000, RENT_RATIONALE, cit_rent_25)
add_adj(
    "adj_2025_legal",
    "Honorarios de defensa del proceso laboral (no recurrentes)",
    "NON_RECURRING_LEGAL",
    "2025",
    280_000,
    "Honorarios extraordinarios ligados a un único proceso judicial (Nota 22). Se normalizan como no recurrentes; "
    "el riesgo del proceso en sí se trata como contingencia, no en el EBITDA.",
    cit_legal_fees,
)
add_adj(
    "adj_2025_personal",
    "Gastos personales de accionistas (club social y vehículos)",
    "PERSONAL_EXPENSES",
    "2025",
    74_000,
    "La Nota 19 identifica cuotas de club y vehículos asignados a accionistas dentro de gastos diversos. "
    "Queda en revisión: falta soporte de si los vehículos tienen uso comercial parcial.",
    cit_personal,
    status="PENDING_REVIEW",
)
add_adj(
    "adj_2025_gain_ppe",
    "Utilidad no recurrente en venta de vehículo",
    "OTHER",
    "2025",
    -38_000,
    "La cuenta 4245 registra una utilidad por venta de activo fijo incluida en otros ingresos operativos. "
    "No es repetible: se resta del EBITDA.",
    cit_gain_ppe,
)

# ---------------------------------------------------------------------------
# Perfil societario
# ---------------------------------------------------------------------------


def fact(label, value, cid, doc_id, page, quote, status="VERIFIED", conf=0.97):
    return {"label": label, "value": value, "status": status, "citation": cite(cid, doc_id, page, quote, None, conf)}


cit_labor = note_cite(
    "cit_n22_pretensiones",
    DOC_EEFF25,
    "Página 16",
    "Las pretensiones ascienden a $850.000. Los asesores legales califican la probabilidad de pérdida como posible; en consecuencia no se ha reconocido provisión.",
)
cit_dian = note_cite(
    "cit_n23_dian",
    DOC_EEFF25,
    "Página 17",
    "En noviembre de 2025 la DIAN notificó requerimiento especial sobre la declaración de renta del año gravable 2022, proponiendo el rechazo de costos por $310.000 más sanción por inexactitud.",
)
cit_shareholders = note_cite(
    "cit_teaser_accionistas",
    DOC_TEASER,
    "Página 2",
    "Composición accionaria: Jorge Enrique Ramírez Gómez 60 %, Gloria Inés Ospina de Ramírez 20 %, María Fernanda Ramírez Ospina 10 %, Andrés Felipe Ramírez Ospina 10 %.",
    0.9,
)

corporate_profile = {
    "legal_name": fact("Razón social", COMPANY, "cit_ccio_razon", DOC_CCIO, "Página 1", f"Razón social: {COMPANY.upper()}"),
    "nit": fact("NIT", NIT, "cit_ccio_nit", DOC_CCIO, "Página 1", f"NIT: {NIT}"),
    "ciiu_primary": fact(
        "CIIU principal",
        "1020 - Procesamiento y conservación de frutas, legumbres, hortalizas y tubérculos",
        "cit_ccio_ciiu",
        DOC_CCIO,
        "Página 1",
        "Código CIIU 1020 - Procesamiento y conservación de frutas, legumbres, hortalizas y tubérculos",
    ),
    "ciiu_secondary": fact(
        "CIIU secundario",
        "4631 - Comercio al por mayor de productos alimenticios",
        "cit_ccio_ciiu2",
        DOC_CCIO,
        "Página 1",
        "Código CIIU 4631 - Comercio al por mayor de productos alimenticios",
    ),
    "domicile": fact("Domicilio", "Rionegro (Antioquia)", "cit_ccio_domicilio", DOC_CCIO, "Página 1", "Domicilio principal: Rionegro (Antioquia)"),
    "incorporation": fact(
        "Constitución",
        "Constituida como Ltda. en 2006 (E.P. 812); transformada a S.A.S. en 2012 (Acta 21)",
        "cit_ccio_constitucion",
        DOC_CCIO,
        "Página 1",
        "Constitución: Escritura Pública No. 812 del 14 de marzo de 2006 como sociedad limitada; transformada en sociedad por acciones simplificada mediante Acta No. 21 de Asamblea del 2 de julio de 2012.",
    ),
    "legal_representative": fact(
        "Representante legal (Gerente)",
        "Jorge Enrique Ramírez Gómez",
        "cit_ccio_gerente",
        DOC_CCIO,
        "Página 2",
        "Gerente (representante legal principal): JORGE ENRIQUE RAMÍREZ GÓMEZ",
    ),
    "alternate_legal_representative": fact(
        "Suplente del Gerente",
        "María Fernanda Ramírez Ospina",
        "cit_ccio_suplente",
        DOC_CCIO,
        "Página 2",
        "Suplente del Gerente: MARÍA FERNANDA RAMÍREZ OSPINA",
    ),
    "statutory_limits": [
        fact(
            "Límite de contratación del Gerente",
            "Requiere autorización de Asamblea para actos o contratos superiores a 500 SMMLV",
            "cit_ccio_limite_500",
            DOC_CCIO,
            "Página 2",
            "El Gerente requerirá autorización previa de la Asamblea General de Accionistas para celebrar actos o contratos cuya cuantía exceda de quinientos (500) salarios mínimos mensuales legales vigentes.",
        ),
        fact(
            "Enajenación o gravamen de activos fijos",
            "Requiere autorización de Asamblea",
            "cit_ccio_activos",
            DOC_CCIO,
            "Página 2",
            "Igualmente requerirá autorización de la Asamblea para enajenar o gravar a cualquier título los activos fijos de la sociedad.",
        ),
        fact(
            "Garantías a terceros o accionistas",
            "Prohibido sin autorización expresa de Asamblea",
            "cit_ccio_garantias",
            DOC_CCIO,
            "Página 2",
            "Le está prohibido constituir a la sociedad como garante de obligaciones de terceros o de sus accionistas sin autorización expresa de la Asamblea.",
        ),
    ],
    "shareholders": [
        {"name": "Jorge Enrique Ramírez Gómez", "ownership_pct": 60.0, "verification_status": "UNVERIFIED", "citation": cit_shareholders},
        {"name": "Gloria Inés Ospina de Ramírez", "ownership_pct": 20.0, "verification_status": "UNVERIFIED", "citation": cit_shareholders},
        {"name": "María Fernanda Ramírez Ospina", "ownership_pct": 10.0, "verification_status": "UNVERIFIED", "citation": cit_shareholders},
        {"name": "Andrés Felipe Ramírez Ospina", "ownership_pct": 10.0, "verification_status": "UNVERIFIED", "citation": cit_shareholders},
    ],
    "legal_proceedings": [
        {
            "id": "lit_laboral_contrato_realidad",
            "proceeding_type": "LABORAL",
            "description": "Proceso laboral ordinario de 11 extrabajadores que reclaman contrato realidad (vinculados vía cooperativa de trabajo asociado 2017-2021).",
            "claimed_amount_cop": 850_000.0 * K,
            "provisioned_amount_cop": 0.0,
            "probability": "POSIBLE",
            "citation": cit_labor,
        },
        {
            "id": "lit_dian_renta_2022",
            "proceeding_type": "TRIBUTARIO",
            "description": "Requerimiento especial DIAN sobre renta 2022: rechazo de costos más sanción por inexactitud (sanción no cuantificada).",
            "claimed_amount_cop": 310_000.0 * K,
            "provisioned_amount_cop": 0.0,
            "probability": "POSIBLE",
            "citation": cit_dian,
        },
    ],
}

# ---------------------------------------------------------------------------
# Ítems ilegibles / no mapeados
# ---------------------------------------------------------------------------

row_2815 = TB_ROW_INDEX[("2025", "2815")]
unreadable = [
    {
        "id": "unr_bp25_2815",
        "description": "Cuenta 2815 Ingresos recibidos para terceros (BP_2025) con valor ilegible '#¡REF!'.",
        "reason": (
            "La celda contiene una referencia rota de Excel. No se imputa ningún valor. El balance de 2025 cuadra sin "
            "esta fila, lo que sugiere un subtotal roto, pero debe confirmarse con el contador."
        ),
        "citation": cite("cit_bp25_2815", DOC_BP, "BP_2025", "2815 | Ingresos recibidos para terceros | #¡REF!", f"C{row_2815}", 0.3),
    },
    {
        "id": "unr_bp23_valorizaciones",
        "description": "Cuentas 1910 Valorizaciones y 3805 Superávit por valorizaciones (BP_2023) por $350.000.000 cada una.",
        "reason": "Saldos heredados del PUC (Decreto 2649/93) no reconocidos bajo NIIF para PYMES; se excluyen del análisis (categoría UNMAPPED).",
        "citation": CITATIONS["cit_bp23_1910"],
    },
]

# ---------------------------------------------------------------------------
# Red flags del agente escéptico (solo cifras citadas literalmente; ratios los calcula el motor)
# ---------------------------------------------------------------------------

cit_enfasis = note_cite(
    "cit_dictamen_enfasis",
    DOC_EEFF25,
    "Página 2",
    "la administración no ha reconocido provisión alguna.",
)
cit_aging_90 = note_cite("cit_n7_vencida_91_180", DOC_EEFF25, "Página 9", "Vencida 91-180 días | 520.000 | 210.000")
cit_aging_180 = note_cite("cit_n7_vencida_180", DOC_EEFF25, "Página 9", "Vencida más de 180 días | 320.000 | 120.000")
cit_reorg = note_cite(
    "cit_n7_reorganizacion",
    DOC_EEFF25,
    "Página 9",
    "La cartera vencida a más de 90 días incluye $620.000 a cargo de Supermercados La Económica del Caribe S.A.S., sociedad admitida a proceso de reorganización empresarial (Ley 1116 de 2006) en septiembre de 2025.",
)
cit_covenant = note_cite(
    "cit_n12_covenant",
    DOC_EEFF25,
    "Página 12",
    "la relación Deuda financiera / EBITDA no debe superar 2,5 veces",
)
cit_acceleration = note_cite(
    "cit_n12_aceleracion",
    DOC_EEFF25,
    "Página 12",
    "El incumplimiento de esta condición faculta al banco para declarar el plazo vencido de la totalidad de las obligaciones.",
)
cit_loans_sh = note_cite(
    "cit_n7_prestamos_socios",
    DOC_EEFF25,
    "Página 9",
    "Deudores varios incluye préstamos a accionistas por $410.000 (2024: $160.000), sin plazo de pago ni intereses pactados.",
)
cit_teaser_ebitda = note_cite("cit_teaser_ebitda", DOC_TEASER, "Página 1", "EBITDA ajustado 2025: COP 3.900 millones.", 0.92)
cit_teaser_growth = note_cite("cit_teaser_crecimiento", DOC_TEASER, "Página 1", "Crecimiento anual de ventas superior al 15 % en los últimos tres años.", 0.92)
cit_teaser_conc = note_cite(
    "cit_teaser_concentracion",
    DOC_TEASER,
    "Página 1",
    "Los tres principales clientes (grandes superficies nacionales) representan el 48 % de las ventas.",
    0.92,
)
cit_capital = note_cite("cit_ccio_acciones", DOC_CCIO, "Página 1", "Número de acciones suscritas: 2.000.000 | Valor nominal: $1.000")
cit_hipoteca = note_cite(
    "cit_n12_hipoteca",
    DOC_EEFF25,
    "Página 12",
    "Los créditos están garantizados con hipoteca abierta de primer grado sobre la planta de producción ubicada en Rionegro, Antioquia.",
)
cit_cooperativa = note_cite(
    "cit_n22_cooperativa",
    DOC_EEFF25,
    "Página 16",
    "reclaman el reconocimiento de contrato realidad con la Compañía y no con la cooperativa de trabajo asociado que los vinculó entre 2017 y 2021.",
)

red_flags = [
    {
        "id": "rf_contingencias",
        "severity": "CRITICAL_DEALBREAKER",
        "domain": "TAX_AND_CONTINGENCIES",
        "title": "Contingencias laboral y tributaria sin provisión",
        "challenge_by_skeptic": (
            "Hay dos procesos calificados como 'posibles' y sin un peso provisionado: la demanda de 11 extrabajadores por "
            "contrato realidad (pretensiones $850.000 miles) y el requerimiento especial de la DIAN sobre renta 2022 "
            "($310.000 miles más una sanción por inexactitud aún sin cuantificar). El revisor fiscal incluyó un párrafo de "
            "énfasis. Si la tercerización vía cooperativa se declara ilegal, el riesgo puede extenderse a otros trabajadores "
            "del mismo periodo. Sin una indemnidad o un escrow, el comprador hereda ese pasivo en su totalidad."
        ),
        "mitigation_question": (
            "¿Cuántas personas en total estuvieron vinculadas por la cooperativa entre 2017 y 2021, y aceptarían los "
            "accionistas un escrow o una cláusula de indemnidad específica por ambos procesos?"
        ),
        "status": "ACTIVE",
        "citations": [cit_labor, cit_cooperativa, cit_dian, cit_enfasis],
    },
    {
        "id": "rf_cartera",
        "severity": "HIGH",
        "domain": "FINANCIAL",
        "title": "Deterioro acelerado de la cartera y cliente en reorganización (Ley 1116)",
        "challenge_by_skeptic": (
            "La cartera vencida a más de 90 días saltó en un año y uno de los clientes de grandes superficies está en "
            "reorganización empresarial con $620.000 miles vencidos. El deterioro registrado en 2025 ($140.000 miles) "
            "parece corto frente a esa exposición: el EBITDA 2025 podría estar sobrestimado por provisiones insuficientes."
        ),
        "mitigation_question": (
            "¿Cuál es el aging de cartera por cliente a diciembre 2025 y qué abonos ha recibido de Supermercados La "
            "Económica del Caribe desde su admisión a reorganización?"
        ),
        "status": "ACTIVE",
        "citations": [cit_aging_90, cit_aging_180, cit_reorg, CITATIONS["cit_bp25_5199"]],
    },
    {
        "id": "rf_covenant",
        "severity": "HIGH",
        "domain": "FINANCIAL",
        "title": "Covenant bancario Deuda financiera / EBITDA ≤ 2,5x con riesgo de aceleración",
        "challenge_by_skeptic": (
            "El covenant se mide sobre estados financieros dictaminados, es decir, sobre EBITDA reportado y no ajustado. "
            "Los ajustes que mejoran nuestra lectura no le sirven al banco. Si la relación se rompe, el banco puede "
            "declarar vencida toda la deuda, que además está garantizada con hipoteca sobre la planta."
        ),
        "mitigation_question": (
            "¿Cómo calcula el banco la 'Deuda financiera' del covenant (incluye leasing y préstamos de socios) y existe "
            "alguna dispensa (waiver) vigente o en trámite para 2025?"
        ),
        "status": "ACTIVE",
        "citations": [cit_covenant, cit_acceleration, cit_hipoteca],
    },
    {
        "id": "rf_caja_socios",
        "severity": "HIGH",
        "domain": "FINANCIAL",
        "title": "Salida de caja hacia accionistas: préstamos sin plazo ni intereses",
        "challenge_by_skeptic": (
            "Los préstamos a accionistas pasaron de $160.000 a $410.000 miles sin plazo ni intereses, mientras el saldo en "
            "bancos cayó. Sumado al arriendo de la bodega del socio y a los salarios de familiares, el patrón sugiere que "
            "la caja de la compañía financia a la familia. Es una fuga de valor que se repetirá si no se corta en el cierre."
        ),
        "mitigation_question": (
            "¿Los accionistas están dispuestos a cancelar los $410 millones prestados antes del cierre o a que se "
            "descuenten del precio?"
        ),
        "status": "ACTIVE",
        "citations": [cit_loans_sh, CITATIONS["cit_bp25_1110"], CITATIONS["cit_bp24_1110"]],
    },
    {
        "id": "rf_teaser_inflado",
        "severity": "HIGH",
        "domain": "COMMERCIAL_MARKET",
        "title": "El teaser sobrestima EBITDA ajustado y crecimiento",
        "challenge_by_skeptic": (
            "El teaser afirma un EBITDA ajustado 2025 de COP 3.900 millones y crecimiento anual superior al 15 %. "
            "Ninguna de las dos cifras se reproduce desde el balance de prueba con ajustes soportados (ver motor "
            "determinista). Si el vendedor ancla precio sobre 3.900 millones, la brecha de expectativas puede romper la "
            "negociación o esconder ajustes agresivos no revelados."
        ),
        "mitigation_question": (
            "¿Puede el asesor compartir el puente de EBITDA ajustado que soporta los COP 3.900 millones, ajuste por ajuste?"
        ),
        "status": "ACTIVE",
        "citations": [cit_teaser_ebitda, cit_teaser_growth],
    },
    {
        "id": "rf_concentracion",
        "severity": "MEDIUM",
        "domain": "COMMERCIAL_MARKET",
        "title": "Concentración de clientes: top 3 = 48 % de ventas",
        "challenge_by_skeptic": (
            "Casi la mitad de las ventas depende de tres grandes superficies con poder de negociación sobre precio y "
            "plazo; uno de los clientes del canal ya está en reorganización. La pérdida de un solo cliente podría borrar "
            "buena parte del EBITDA."
        ),
        "mitigation_question": (
            "¿Qué contratos o acuerdos comerciales vigentes hay con los tres principales clientes y cuáles son sus plazos "
            "de pago y condiciones de terminación?"
        ),
        "status": "ACTIVE",
        "citations": [cit_teaser_conc, cit_reorg],
    },
    {
        "id": "rf_accionistas",
        "severity": "MEDIUM",
        "domain": "CORPORATE_LEGAL",
        "title": "Composición accionaria no verificada",
        "challenge_by_skeptic": (
            "En una S.A.S. el certificado de Cámara de Comercio no identifica a los accionistas: solo informa número de "
            "acciones. La composición 60/20/10/10 proviene únicamente del teaser. Sin libro de accionistas no sabemos si "
            "hay prendas, usufructos o acuerdos de accionistas que limiten la venta del 40 %."
        ),
        "mitigation_question": "¿Pueden enviar copia del libro de registro de accionistas y de cualquier acuerdo de accionistas vigente?",
        "status": "ACTIVE",
        "citations": [cit_shareholders, cit_capital],
    },
    {
        "id": "rf_gobierno",
        "severity": "MEDIUM",
        "domain": "CORPORATE_LEGAL",
        "title": "Gobierno corporativo concentrado en la familia y garantías sobre activos",
        "challenge_by_skeptic": (
            "Gerente y suplente son padre e hija; no hay junta directiva inscrita. La planta ya está hipotecada y gravar "
            "activos exige autorización de Asamblea, que hoy controla la familia. El inversionista minoritario necesitará "
            "derechos de veto contractuales."
        ),
        "mitigation_question": "¿Estarían dispuestos a crear una junta directiva con un miembro designado por el inversionista y una lista de decisiones reservadas?",
        "status": "ACTIVE",
        "citations": [CITATIONS["cit_ccio_gerente"], CITATIONS["cit_ccio_suplente"], CITATIONS["cit_ccio_activos"], cit_hipoteca],
    },
]

missing_info = [
    {
        "id": "mi_libro_accionistas",
        "category": "Societario",
        "requested_document_or_clarification": "Copia del libro de registro de accionistas y de cualquier acuerdo de accionistas vigente.",
        "why_it_matters_plain_spanish": "Necesitamos confirmar quién es dueño de qué porcentaje y que las acciones no estén prendadas, para saber que quien vende realmente puede vender.",
        "priority": "MUST_HAVE_FOR_IC",
    },
    {
        "id": "mi_concepto_laboral",
        "category": "Contingencias",
        "requested_document_or_clarification": "Concepto escrito del abogado sobre el proceso laboral (etapa, cuantía actualizada, probabilidad) y número total de personas vinculadas por la cooperativa entre 2017 y 2021.",
        "why_it_matters_plain_spanish": "Queremos entender cuánto podría costar en el peor caso para acordar desde ya cómo se cubre, sin que eso afecte la negociación más adelante.",
        "priority": "MUST_HAVE_FOR_IC",
    },
    {
        "id": "mi_dian",
        "category": "Tributario",
        "requested_document_or_clarification": "Copia del requerimiento especial de la DIAN (renta 2022) y de la respuesta radicada.",
        "why_it_matters_plain_spanish": "Nos ayuda a dimensionar el valor de la posible sanción y a ver qué tan sólida es la defensa de la empresa.",
        "priority": "MUST_HAVE_FOR_IC",
    },
    {
        "id": "mi_aging_cartera",
        "category": "Financiero",
        "requested_document_or_clarification": "Antigüedad de cartera por cliente a diciembre 2025 y estado de los pagos de Supermercados La Económica del Caribe.",
        "why_it_matters_plain_spanish": "Nos permite saber cuánta de la plata que le deben a la empresa realmente va a entrar a caja.",
        "priority": "MUST_HAVE_FOR_IC",
    },
    {
        "id": "mi_creditos",
        "category": "Financiero",
        "requested_document_or_clarification": "Contratos de crédito y leasing vigentes, con la fórmula del indicador Deuda/EBITDA y cualquier dispensa (waiver) del banco.",
        "why_it_matters_plain_spanish": "Queremos asegurarnos de que la entrada de un socio no active ninguna cláusula del banco que obligue a pagar los créditos de inmediato.",
        "priority": "MUST_HAVE_FOR_IC",
    },
    {
        "id": "mi_contrato_bodega",
        "category": "Partes relacionadas",
        "requested_document_or_clarification": "Contrato de arrendamiento de la bodega de Rionegro con el accionista y disposición a renegociarlo a canon de mercado.",
        "why_it_matters_plain_spanish": "El arriendo está por encima del precio de mercado; queremos ver si se puede ajustar para que la empresa refleje su rentabilidad real.",
        "priority": "MUST_HAVE_FOR_IC",
    },
    {
        "id": "mi_ventas_cliente",
        "category": "Comercial",
        "requested_document_or_clarification": "Ventas mensuales 2024-2025 por cliente y por línea de producto.",
        "why_it_matters_plain_spanish": "Nos ayuda a entender la estacionalidad del negocio y qué tanto depende de los clientes más grandes.",
        "priority": "NICE_TO_HAVE",
    },
    {
        "id": "mi_puente_teaser",
        "category": "Financiero",
        "requested_document_or_clarification": "Detalle de los ajustes que componen el EBITDA ajustado de COP 3.900 millones del teaser.",
        "why_it_matters_plain_spanish": "Queremos llegar al mismo número que ustedes para no tener diferencias de expectativas en el precio.",
        "priority": "NICE_TO_HAVE",
    },
    {
        "id": "mi_declaraciones_renta",
        "category": "Tributario",
        "requested_document_or_clarification": "Declaraciones de renta 2023 y 2024 con sus soportes de pago.",
        "why_it_matters_plain_spanish": "Confirman que los impuestos de los últimos años están al día y que las cifras contables coinciden con lo declarado.",
        "priority": "NICE_TO_HAVE",
    },
]

# ---------------------------------------------------------------------------
# Memo (plantilla del agente redactor; las cifras calculadas las inyecta el renderizador determinista)
# ---------------------------------------------------------------------------

MEMO = f"""# Memo de Screening — {COMPANY}

**Para:** Comité de Inversión · **Etapa:** Screening preliminar · **Periodo analizado:** 2023–2025
**Nota metodológica:** las cifras calculadas provienen del motor financiero determinista (0 llamadas a LLM). Cada cifra fuente lleva su cita.

## 1. Resumen ejecutivo

{COMPANY} (NIT {NIT} [[cite:cit_ccio_nit]]) procesa y conserva frutas y hortalizas (CIIU 1020 [[cite:cit_ccio_ciiu]]) desde su planta en Rionegro, Antioquia [[cite:cit_ccio_domicilio]]. En 2025 registró ingresos netos de {{{{metric:revenue:2025}}}} [[cite:cit_bp25_4120]] [[cite:cit_bp25_4175]], un crecimiento de {{{{metric:revenue_growth_yoy_pct:2025}}}} frente a 2024 y una tasa compuesta 2023–2025 de {{{{growth:revenue_cagr_pct}}}}.

El EBITDA reportado 2025 fue {{{{metric:ebitda_reported:2025}}}} (margen {{{{metric:ebitda_reported_margin_pct:2025}}}}). Tras los ajustes aceptados por el analista, el EBITDA ajustado es {{{{metric:ebitda_adjusted:2025}}}} (margen {{{{metric:ebitda_adjusted_margin_pct:2025}}}}), frente a COP 3.900 millones que afirma el teaser [[cite:cit_teaser_ebitda]].

**Recomendación preliminar:** continuar a due diligence confirmatoria, condicionada a (i) cuantificar y blindar contractualmente las contingencias laboral y tributaria, y (ii) verificar el cumplimiento del covenant bancario.

## 2. Tesis de inversión

- **Categoría defensiva con escala regional:** más de 18 años de operación y planta con certificación sanitaria (afirmación del teaser, pendiente de verificar) [[cite:cit_teaser_trayectoria]].
- **Crecimiento sostenido:** ingresos de {{{{metric:revenue:2023}}}} en 2023 a {{{{metric:revenue:2025}}}} en 2025 [[cite:cit_bp23_4120]] [[cite:cit_bp25_4120]]. El teaser afirma crecimiento superior al 15 % anual [[cite:cit_teaser_crecimiento]]; el motor calcula {{{{growth:revenue_cagr_pct}}}}.
- **Palanca de normalización:** salarios de familiares sin cargo operativo [[cite:cit_n24_familiares_2025]] y un arriendo al socio por encima del mercado [[cite:cit_avaluo_2025]] son costos que un nuevo gobierno corporativo puede eliminar.
- **Margen bruto** de {{{{metric:gross_margin_pct:2025}}}} vs. mediana sectorial de {{{{benchmark:gross_margin_pct:median}}}}.

## 3. Calidad del EBITDA

| Concepto | 2025 |
|---|---|
| EBITDA reportado | {{{{metric:ebitda_reported:2025}}}} |
| Ajustes aceptados | {{{{bridge:2025:total_accepted}}}} |
| Ajustes pendientes de revisión (excluidos) | {{{{bridge:2025:total_pending}}}} |
| **EBITDA ajustado** | **{{{{metric:ebitda_adjusted:2025}}}}** |

- Salarios de familiares sin cargo operativo [[cite:cit_n24_familiares_2025]].
- Exceso de arriendo de bodega pagado al socio, según avalúo independiente [[cite:cit_avaluo_2025]].
- Honorarios de defensa del proceso laboral, no recurrentes [[cite:cit_n22_honorarios]].
- Utilidad en venta de vehículo, restada por no recurrente [[cite:cit_bp25_4245]].
- En revisión: gastos personales de accionistas [[cite:cit_n19_personales]].

El deterioro de cartera de 2025 [[cite:cit_bp25_5199]] podría ser insuficiente frente a la exposición a un cliente en reorganización [[cite:cit_n7_reorganizacion]]; no se ajustó el EBITDA por ese riesgo, se trata como red flag.

## 4. Valoración preliminar (múltiplos EV/EBITDA, sector {{{{valuation:sector_label}}}})

| Escenario | Múltiplo | Enterprise Value | Deuda neta | Equity Value |
|---|---|---|---|---|
| Conservador (P25) | {{{{valuation:CONSERVADOR:multiple}}}} | {{{{valuation:CONSERVADOR:enterprise_value}}}} | {{{{valuation:CONSERVADOR:net_debt}}}} | {{{{valuation:CONSERVADOR:equity_value}}}} |
| Base (Mediana) | {{{{valuation:BASE:multiple}}}} | {{{{valuation:BASE:enterprise_value}}}} | {{{{valuation:BASE:net_debt}}}} | {{{{valuation:BASE:equity_value}}}} |
| Optimista (P75) | {{{{valuation:OPTIMISTA:multiple}}}} | {{{{valuation:OPTIMISTA:enterprise_value}}}} | {{{{valuation:OPTIMISTA:net_debt}}}} | {{{{valuation:OPTIMISTA:equity_value}}}} |

La deuda neta incluye pagarés bancarios, leasing y préstamos de accionistas [[cite:cit_bp25_21051001]] [[cite:cit_bp25_21051002]] [[cite:cit_bp25_2120]] [[cite:cit_bp25_2355]]. Deuda neta / EBITDA ajustado 2025: {{{{metric:net_debt_to_ebitda_adjusted:2025}}}} (reportado: {{{{metric:net_debt_to_ebitda_reported:2025}}}}). Los múltiplos son referenciales y deben recalibrarse antes del Comité.

## 5. Riesgos críticos

1. **Contingencias sin provisión:** proceso laboral [[cite:cit_n22_pretensiones]] y requerimiento DIAN [[cite:cit_n23_dian]] suman {{{{contingencies:unprovisioned}}}}, equivalente a {{{{contingencies:pct_adj_ebitda}}}} del EBITDA ajustado. El revisor fiscal incluyó párrafo de énfasis [[cite:cit_dictamen_enfasis]].
2. **Cartera:** días de cartera de {{{{metric:dso_days:2024}}}} en 2024 a {{{{metric:dso_days:2025}}}} en 2025; cliente en reorganización [[cite:cit_n7_reorganizacion]].
3. **Covenant bancario:** Deuda financiera / EBITDA ≤ 2,5x [[cite:cit_n12_covenant]] con cláusula de aceleración [[cite:cit_n12_aceleracion]]. Deuda neta / EBITDA reportado 2025: {{{{metric:net_debt_to_ebitda_reported:2025}}}}.
4. **Caja:** efectivo de {{{{metric:cash:2024}}}} en 2024 a {{{{metric:cash:2025}}}} en 2025, con préstamos a accionistas sin plazo [[cite:cit_n7_prestamos_socios]].
5. **Concentración:** top 3 clientes = 48 % de ventas, según teaser [[cite:cit_teaser_concentracion]].

## 6. Próximos pasos

- Enviar al empresario la solicitud de información faltante (libro de accionistas, concepto laboral, requerimiento DIAN, aging por cliente, contratos de crédito).
- Recalcular el EBITDA ajustado al resolver el ajuste pendiente de gastos personales.
- Estructurar escrow o indemnidad específica por contingencias antes de cualquier oferta vinculante.
"""

# ---------------------------------------------------------------------------
# Ensamblar, validar y escribir
# ---------------------------------------------------------------------------

seed = {
    "deal_id": "demo-alimentos-conservas-oriente",
    "created_at": datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
    "llm_mode": "SEED_FALLBACK",
    "company_name": COMPANY,
    "nit": NIT,
    "ciiu_code": "1020",
    "city": "Rionegro, Antioquia",
    "periods": PERIODS,
    "documents": list(DOCS.values()),
    "mapped_accounts": mapped_accounts,
    "unreadable_or_unmapped_items": unreadable,
    "ebitda_adjustments": ADJ,
    "corporate_profile": corporate_profile,
    "red_flags": red_flags,
    "missing_info": missing_info,
    "memo_markdown_template": MEMO,
    "memo_citations": [
        note_cite(
            "cit_teaser_trayectoria",
            DOC_TEASER,
            "Página 1",
            "Más de 18 años en el mercado, con planta certificada BPM e INVIMA en Rionegro y portafolio de 64 referencias (conservas, mermeladas, salsas y pulpas).",
            0.9,
        )
    ],
}


def main() -> None:
    dossier = DealDossier.model_validate(seed)  # falla si algo rompe el esquema
    OUTPUT.write_text(json.dumps(dossier.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK -> {OUTPUT.relative_to(BACKEND_DIR)}")
    print(f"   documentos={len(DOCS)} citas={len(CITATIONS)} cuentas={len(mapped_accounts)} ajustes={len(ADJ)}")
    for p in PERIODS:
        print(f"   {p}: utilidad neta={NET_INCOME[p]:,} miles | bancos={acct('1110')[p]:,} miles")


if __name__ == "__main__":
    main()
