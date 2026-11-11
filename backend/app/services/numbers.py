"""Lectura determinista de cifras en formatos colombianos y anglosajones (sin LLM)."""

from __future__ import annotations

import re
from typing import Optional

_NUMBER_TOKEN = re.compile(r"\(?-?\$?\s?\d[\d.,]*\)?-?")
_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")
EXCEL_ERRORS = ("#¡REF!", "#REF!", "#¡VALOR!", "#VALUE!", "#N/A", "#¡DIV/0!", "#DIV/0!", "#¿NOMBRE?", "#NAME?", "#NUM!", "#¡NUM!")


def parse_number(value: object) -> Optional[float]:
    """Convierte '28.790.000.000,00', '(1.234)', '-1,234.50', '$ 45.000' o un número en float.

    Devuelve None si el valor no es un número legible (texto, vacío o error de Excel).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or any(err in text.upper() for err in EXCEL_ERRORS):
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = text.replace("COP", "").replace("$", "").replace(" ", "").replace(" ", "")
    if text.endswith("-"):
        negative, text = not negative, text[:-1]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    if not text or not re.fullmatch(r"[\d.,]+", text) or not text[0].isdigit():
        return None
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "") if _THOUSANDS_COMMA.match(text) else text.replace(",", ".")
    elif "." in text and _THOUSANDS_DOT.match(text):
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def find_numbers(text: str) -> list[tuple[str, float]]:
    """Todos los tokens numéricos de un texto con su valor interpretado."""
    found = []
    for match in _NUMBER_TOKEN.finditer(text):
        raw = match.group(0).strip().rstrip(".,")  # puntuación de fin de frase: "$850.000."
        value = parse_number(raw)
        if value is not None:
            found.append((raw, value))
    return found


def amount_supported_by_text(amount_cop: float, text: str, multipliers: tuple[float, ...] = (1.0, 1_000.0, 1_000_000.0)) -> bool:
    """True si |amount_cop| aparece literalmente en el texto en COP, miles o millones de COP."""
    target = abs(amount_cop)
    if target == 0:
        return True
    for _, value in find_numbers(text):
        for mult in multipliers:
            if abs(abs(value) * mult - target) <= max(0.5, target * 1e-9):
                return True
    return False
