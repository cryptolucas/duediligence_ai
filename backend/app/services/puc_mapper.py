"""Mapeo determinista PUC colombiano -> categoría estándar y normalización de signos.

Es la línea base del Agente de Ingesta: clasifica por prefijo del código PUC (Decreto 2650/93,
usado aún por Siigo / World Office como plan de cuentas bajo NIIF Grupo 2). El LLM, cuando está
disponible, solo revisa la clasificación de las cuentas ambiguas; los valores SIEMPRE salen del
parser y de este módulo, nunca del LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from app.schemas.deal import ASSET_CATEGORIES, LIABILITY_CATEGORIES

DEBIT_NATURE_CATEGORIES = frozenset({*ASSET_CATEGORIES, "COGS", "SGA", "DA", "TAXES", "NET_INTEREST"})
CREDIT_NATURE_CATEGORIES = frozenset({*LIABILITY_CATEGORIES, "EQUITY", "REVENUE", "OTHER_OP_INCOME_EXP"})

# Cuentas cuya naturaleza contable es opuesta a la de su clase (correctoras).
CONTRA_NATURE_PREFIXES = {
    "1399": "C", "1592": "C", "1597": "C", "1598": "C", "1599": "C", "1698": "C", "1699": "C",
    "4175": "D", "3610": "D", "3710": "D",
}

SignConvention = Literal["DEBIT_POSITIVE", "NATURAL_POSITIVE"]


@dataclass(frozen=True)
class RuleMapping:
    category: str
    rationale: str
    confidence: float


# (prefijo, categoría, explicación, confianza) — se evalúa el prefijo más largo primero.
_RULES: list[tuple[str, str, str, float]] = [
    ("11", "CASH", "Grupo 11 Disponible (caja, bancos, equivalentes)", 0.97),
    ("12", "OTHER_CURRENT_ASSETS", "Grupo 12 Inversiones; se asume corriente, validar liquidez", 0.6),
    ("1305", "ACCOUNTS_RECEIVABLE", "Cuenta 1305 Clientes: cartera comercial", 0.97),
    ("1310", "ACCOUNTS_RECEIVABLE", "Cuenta 1310 Cuentas corrientes comerciales", 0.85),
    ("1390", "ACCOUNTS_RECEIVABLE", "Cuenta 1390 Deudas de difícil cobro", 0.85),
    ("1399", "ACCOUNTS_RECEIVABLE", "Cuenta 1399 Deterioro de deudores (correctora)", 0.95),
    ("1325", "OTHER_CURRENT_ASSETS", "Cuenta 1325 Cuentas por cobrar a socios: no es cartera comercial", 0.9),
    ("13", "OTHER_CURRENT_ASSETS", "Grupo 13 Deudores no comerciales (anticipos, impuestos, varios)", 0.8),
    ("14", "INVENTORY", "Grupo 14 Inventarios", 0.97),
    ("15", "PPE_AND_INTANGIBLES", "Grupo 15 Propiedades, planta y equipo", 0.95),
    ("16", "PPE_AND_INTANGIBLES", "Grupo 16 Intangibles", 0.9),
    ("17", "OTHER_CURRENT_ASSETS", "Grupo 17 Diferidos / gastos pagados por anticipado", 0.6),
    ("18", "PPE_AND_INTANGIBLES", "Grupo 18 Otros activos no corrientes", 0.55),
    ("19", "UNMAPPED", "Grupo 19 Valorizaciones (Decreto 2649/93): no se reconocen bajo NIIF para PYMES", 0.9),
    ("2355", "LONG_TERM_DEBT", "Cuenta 2355 Deudas con accionistas: se trata como deuda (debt-like) por prudencia", 0.85),
    ("21", "SHORT_TERM_DEBT", "Grupo 21 Obligaciones financieras; corriente salvo que el nombre indique largo plazo", 0.7),
    ("22", "ACCOUNTS_PAYABLE", "Grupo 22 Proveedores", 0.97),
    ("23", "OTHER_CURRENT_LIABILITIES", "Grupo 23 Cuentas por pagar", 0.9),
    ("24", "OTHER_CURRENT_LIABILITIES", "Grupo 24 Impuestos, gravámenes y tasas", 0.95),
    ("25", "OTHER_CURRENT_LIABILITIES", "Grupo 25 Obligaciones laborales", 0.95),
    ("26", "OTHER_CURRENT_LIABILITIES", "Grupo 26 Pasivos estimados y provisiones", 0.85),
    ("27", "OTHER_CURRENT_LIABILITIES", "Grupo 27 Diferidos", 0.7),
    ("28", "OTHER_CURRENT_LIABILITIES", "Grupo 28 Otros pasivos (anticipos recibidos, ingresos para terceros)", 0.85),
    ("29", "LONG_TERM_DEBT", "Grupo 29 Bonos y papeles comerciales", 0.85),
    ("38", "UNMAPPED", "Grupo 38 Superávit por valorizaciones: no reconocido bajo NIIF para PYMES", 0.9),
    ("3", "EQUITY", "Clase 3 Patrimonio", 0.95),
    ("4175", "REVENUE", "Cuenta 4175 Devoluciones en ventas: reduce ingresos", 0.97),
    ("41", "REVENUE", "Grupo 41 Ingresos operacionales", 0.97),
    ("4210", "NET_INTEREST", "Cuenta 4210 Ingresos financieros: se netean con gastos financieros", 0.95),
    ("42", "OTHER_OP_INCOME_EXP", "Grupo 42 Ingresos no operacionales (recuperaciones, utilidad en venta de activos)", 0.8),
    ("47", "UNMAPPED", "Grupo 47 Ajustes por inflación (derogado)", 0.9),
    ("5160", "DA", "Cuenta 5160 Depreciaciones (administración)", 0.97),
    ("5165", "DA", "Cuenta 5165 Amortizaciones (administración)", 0.97),
    ("5260", "DA", "Cuenta 5260 Depreciaciones (ventas)", 0.97),
    ("5265", "DA", "Cuenta 5265 Amortizaciones (ventas)", 0.97),
    ("51", "SGA", "Grupo 51 Gastos operacionales de administración", 0.95),
    ("52", "SGA", "Grupo 52 Gastos operacionales de ventas", 0.95),
    ("5305", "NET_INTEREST", "Cuenta 5305 Gastos financieros", 0.95),
    ("53", "OTHER_OP_INCOME_EXP", "Grupo 53 Gastos no operacionales", 0.8),
    ("54", "TAXES", "Grupo 54 Impuesto de renta y complementarios", 0.97),
    ("59", "UNMAPPED", "Grupo 59 Ganancias y pérdidas (cuenta de cierre)", 0.9),
    ("61", "COGS", "Grupo 61 Costo de ventas", 0.95),
    ("62", "COGS", "Grupo 62 Compras (inventario periódico)", 0.6),
    ("7", "UNMAPPED", "Clase 7 Costos de producción: se asume trasladada al 61 al cierre; validar para evitar doble conteo", 0.6),
    ("8", "UNMAPPED", "Clase 8 Cuentas de orden deudoras", 0.97),
    ("9", "UNMAPPED", "Clase 9 Cuentas de orden acreedoras", 0.97),
]
_RULES.sort(key=lambda r: len(r[0]), reverse=True)
_LONG_TERM_RE = re.compile(r"largo\s*plazo|no\s*corriente|\blp\b|l\.p\.", re.IGNORECASE)


def rule_based_mapping(code: str, name: str = "") -> RuleMapping:
    for prefix, category, explanation, confidence in _RULES:
        if code.startswith(prefix):
            if category == "SHORT_TERM_DEBT" and _LONG_TERM_RE.search(name or ""):
                return RuleMapping("LONG_TERM_DEBT", f"PUC {code}: {explanation}. El nombre indica porción no corriente.", 0.85)
            return RuleMapping(category, f"PUC {code}: {explanation}.", confidence)
    return RuleMapping("UNMAPPED", f"Código {code} sin regla PUC conocida; requiere revisión.", 0.2)


def natural_nature(code: str) -> str:
    """Naturaleza contable del PUC: 'D' (débito) o 'C' (crédito)."""
    for prefix, nature in CONTRA_NATURE_PREFIXES.items():
        if code.startswith(prefix):
            return nature
    return "D" if code[:1] in ("1", "5", "6", "7", "8") else "C"


def detect_sign_convention(rows: Iterable[tuple[str, float]]) -> SignConvention:
    """Siigo y World Office suelen exportar saldos crédito con signo negativo (DEBIT_POSITIVE).

    Si la mayoría de saldos de clases 2, 3 y 4 son negativos, el archivo usa DEBIT_POSITIVE; si no,
    asumimos que todos los saldos vienen positivos según su naturaleza (NATURAL_POSITIVE).
    """
    credit_class = [value for code, value in rows if code[:1] in ("2", "3", "4") and value]
    negatives = sum(1 for v in credit_class if v < 0)
    return "DEBIT_POSITIVE" if credit_class and negatives >= len(credit_class) / 2 else "NATURAL_POSITIVE"


def to_engine_value(code: str, category: str, display_value: float, convention: SignConvention) -> float:
    """Convierte el saldo mostrado a la convención de signos del motor (ver app/schemas/deal.py)."""
    if convention == "DEBIT_POSITIVE":
        debit_positive = display_value
    else:
        debit_positive = display_value if natural_nature(code) == "D" else -display_value
    if category in DEBIT_NATURE_CATEGORIES:
        return debit_positive
    if category in CREDIT_NATURE_CATEGORIES:
        return -debit_positive
    return debit_positive  # UNMAPPED: se conserva el signo débito-positivo como referencia


def sign_note(convention: SignConvention, category: str) -> str:
    if category == "UNMAPPED":
        return ""
    if convention == "DEBIT_POSITIVE" and category in CREDIT_NATURE_CATEGORIES:
        return " Saldo crédito exportado con signo negativo; se invierte según la convención del motor."
    return ""


def is_pre_closing(codes: Iterable[str]) -> bool:
    """Balance de prueba pre-cierre: tiene cuentas de resultado (4, 5, 6) y no tiene 3605/3610."""
    codes = list(codes)
    has_pnl = any(c[:1] in ("4", "5", "6") for c in codes)
    has_result = any(c.startswith(("3605", "3610")) for c in codes)
    return has_pnl and not has_result
