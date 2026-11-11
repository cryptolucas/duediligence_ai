"""Extracción de texto y coordenadas de PDF, Excel (XLSX) y CSV — 100 % determinista.

Salida: ``ParsedDocument`` con
* ``source``: ``SourceDocument`` con el texto por página/hoja (base de toda cita literal).
  - PDF: una página por hoja física ("Página N"); las palabras se reagrupan por renglón visual y las
    columnas separadas por espacios amplios se unen con " | ", de modo que una fila de un estado
    financiero queda como "Efectivo y equivalentes (Nota 5) | 545.000 | 1.159.000". Se guardan
    las coordenadas de cada línea (``line_boxes``).
  - Excel/CSV: cada fila no vacía se serializa como "Fila N | valor | valor | ...".
* ``trial_balance_rows``: filas estructuradas de balances de prueba (código PUC, nombre, saldo y celda),
  detectando encabezados, columna de saldo final, periodo y cuentas hoja (evita doble conteo de
  niveles agregados 1 / 11 / 1105 / 110505 que exportan Siigo y World Office).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Optional

from pydantic import BaseModel, Field

from app.schemas.deal import DocumentPage, LineBox, SourceDocument
from app.services.numbers import parse_number

SUPPORTED_EXTENSIONS = {".pdf": "PDF", ".xlsx": "XLSX", ".xlsm": "XLSX", ".csv": "CSV"}
MAX_ROWS_PER_SHEET = 10_000
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
CODE_RE = re.compile(r"^\d{1,10}$")


class UnsupportedDocumentError(ValueError):
    pass


class TrialBalanceRow(BaseModel):
    sheet: str
    row: int
    period: str
    code: str
    name: str
    display_value: Optional[float] = Field(None, description="Saldo tal como aparece (None si es ilegible).")
    raw_value_text: str
    cell_ref: str
    quote: str = Field(..., description="Subcadena literal de la página: la fila serializada.")
    is_leaf: bool = True


class ParsedDocument(BaseModel):
    source: SourceDocument
    trial_balance_rows: List[TrialBalanceRow] = Field(default_factory=list)
    scanned_pages: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "VERDADERO" if value else "FALSO"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}"
    return _nfc(str(value)).replace("\n", " ").replace("|", "/").strip()


def guess_document_type(file_name: str, text_sample: str, file_format: str) -> str:
    haystack = f"{file_name} {text_sample[:6000]}".lower()
    if file_format in ("XLSX", "CSV") and re.search(r"balance\s*de\s*prueba|saldo\s*final|nuevo\s*saldo|auxiliar|bp_", haystack):
        return "TRIAL_BALANCE_XLSX"
    if re.search(r"existencia\s+y\s+representaci|c[áa]mara\s+de\s+comercio|matr[íi]cula\s+mercantil", haystack):
        return "CHAMBER_OF_COMMERCE_CERT"
    if "teaser" in haystack or "oportunidad de inversi" in haystack:
        return "TEASER"
    if re.search(r"aval[úu]o|canon de mercado", haystack):
        return "APPRAISAL"
    if re.search(r"estados?\s+financieros|situaci[óo]n\s+financiera|estado\s+de\s+resultados|notas?\s+a\s+los|revisor\s+fiscal|eeff", haystack):
        return "FINANCIAL_STATEMENTS_PDF" if file_format == "PDF" else "TRIAL_BALANCE_XLSX"
    if file_format in ("XLSX", "CSV"):
        return "TRIAL_BALANCE_XLSX"
    return "OTHER"


def guess_units(text_sample: str, file_format: str) -> str:
    sample = text_sample[:20000].lower()
    if re.search(r"miles\s+de\s+pesos|en\s+miles|cifras\s+en\s+miles", sample):
        return "Miles de COP"
    if re.search(r"millones\s+de\s+pesos|cop\s+millones|en\s+millones", sample):
        return "Millones de COP"
    return "COP"


UNIT_MULTIPLIERS = {"COP": 1.0, "Miles de COP": 1_000.0, "Millones de COP": 1_000_000.0, "COP millones": 1_000_000.0}


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _group_words_into_lines(words: list[tuple]) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Agrupa palabras (x0, y0, x1, y1, texto, ...) por renglón visual y separa columnas con ' | '."""
    if not words:
        return []
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    heights = sorted(w[3] - w[1] for w in words)
    tol = max(1.5, heights[len(heights) // 2] * 0.55)
    rows: list[list[tuple]] = []
    current: list[tuple] = []
    current_y: Optional[float] = None
    for w in words:
        y = (w[1] + w[3]) / 2
        if current_y is None or abs(y - current_y) <= tol:
            current.append(w)
            current_y = y if current_y is None else (current_y * (len(current) - 1) + y) / len(current)
        else:
            rows.append(current)
            current, current_y = [w], y
    if current:
        rows.append(current)

    lines = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        char_w = sum((w[2] - w[0]) / max(len(w[4]), 1) for w in row) / len(row)
        parts: list[str] = [row[0][4]]
        for prev, nxt in zip(row, row[1:]):
            gap = nxt[0] - prev[2]
            parts.append(" | " if gap > max(char_w * 3.0, 12.0) else " ")
            parts.append(nxt[4])
        bbox = (min(w[0] for w in row), min(w[1] for w in row), max(w[2] for w in row), max(w[3] for w in row))
        lines.append((_nfc("".join(parts)), bbox))
    return lines


def parse_pdf(path: Path, document_id: str, display_name: str) -> ParsedDocument:
    pages: list[DocumentPage] = []
    scanned: list[str] = []
    warnings: list[str] = []
    try:
        import pymupdf as fitz  # PyMuPDF
    except ImportError:
        fitz = None

    if fitz is not None:
        with fitz.open(path) as pdf:
            for index, page in enumerate(pdf, start=1):
                name = f"Página {index}"
                lines = _group_words_into_lines(page.get_text("words"))
                if not lines:
                    if page.get_images():
                        scanned.append(name)
                    pages.append(DocumentPage(page_or_sheet=name, content="", width=page.rect.width, height=page.rect.height))
                    continue
                pages.append(
                    DocumentPage(
                        page_or_sheet=name,
                        content="\n".join(text for text, _ in lines),
                        width=round(page.rect.width, 2),
                        height=round(page.rect.height, 2),
                        line_boxes=[
                            LineBox(line=i, x0=round(b[0], 2), y0=round(b[1], 2), x1=round(b[2], 2), y1=round(b[3], 2))
                            for i, (_, b) in enumerate(lines, start=1)
                        ],
                    )
                )
    else:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                name = f"Página {index}"
                words = [(w["x0"], w["top"], w["x1"], w["bottom"], w["text"]) for w in page.extract_words()]
                lines = _group_words_into_lines(words)
                if not lines and page.images:
                    scanned.append(name)
                pages.append(
                    DocumentPage(
                        page_or_sheet=name,
                        content="\n".join(t for t, _ in lines),
                        width=float(page.width),
                        height=float(page.height),
                        line_boxes=[
                            LineBox(line=i, x0=b[0], y0=b[1], x1=b[2], y1=b[3]) for i, (_, b) in enumerate(lines, start=1)
                        ],
                    )
                )
    if scanned:
        warnings.append(f"Páginas sin capa de texto (escaneadas, requieren OCR): {', '.join(scanned)}.")
    text_sample = "\n".join(p.content for p in pages[:6])
    doc_type = guess_document_type(display_name, text_sample, "PDF")
    source = SourceDocument(
        document_id=document_id,
        document_name=display_name,
        document_type=doc_type,
        file_format="PDF",
        description=f"PDF de {len(pages)} página(s) cargado por el usuario.",
        reported_units=guess_units(text_sample, "PDF"),
        pages=pages or [DocumentPage(page_or_sheet="Página 1", content="")],
    )
    return ParsedDocument(source=source, scanned_pages=scanned, warnings=warnings)


# ---------------------------------------------------------------------------
# Hojas de cálculo (XLSX / CSV)
# ---------------------------------------------------------------------------

Row = tuple[int, list[tuple[int, object]]]  # (número de fila 1-based, [(índice de columna 0-based, valor)])


def _sheet_to_page(sheet_name: str, rows: list[Row]) -> tuple[DocumentPage, dict[int, str]]:
    """Serializa filas como 'Fila N | v1 | v2'. Devuelve la página y el texto por fila (sin prefijo)."""
    lines: list[str] = []
    row_text: dict[int, str] = {}
    for row_idx, cells in rows:
        texts = [cell_text(v) for _, v in cells]
        texts = [t for t in texts if t]
        if not texts:
            continue
        joined = " | ".join(texts)
        row_text[row_idx] = joined
        lines.append(f"Fila {row_idx} | {joined}")
    return DocumentPage(page_or_sheet=sheet_name, content="\n".join(lines)), row_text


def _is_code(value: object) -> Optional[str]:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip() if value is not None else ""
    return text if CODE_RE.match(text) else None


def _detect_period(sheet_name: str, header_text: str, file_name: str) -> Optional[str]:
    for source in (sheet_name, header_text, file_name):
        years = YEAR_RE.findall(source)
        if years:
            return max(years)
    return None


def extract_trial_balance(
    sheet_name: str, rows: list[Row], row_text: dict[int, str], file_name: str
) -> tuple[list[TrialBalanceRow], list[str]]:
    """Detecta la estructura de un balance de prueba y devuelve sus filas de cuentas."""
    warnings: list[str] = []
    header_idx: Optional[int] = None
    code_col = name_col = None
    value_cols: dict[str, int] = {}  # periodo -> columna
    single_value_col: Optional[int] = None

    for pos, (row_idx, cells) in enumerate(rows[:25]):
        labels = {col: cell_text(v).lower() for col, v in cells if isinstance(v, str)}
        code_candidates = [c for c, t in labels.items() if re.search(r"c[óo]d", t)]
        if not code_candidates and not any(t in ("cuenta", "cuentas") for t in labels.values()):
            continue
        header_idx = pos
        code_col = code_candidates[0] if code_candidates else next(c for c, t in labels.items() if t in ("cuenta", "cuentas"))
        name_col = next(
            (c for c, t in labels.items() if c != code_col and re.search(r"nombre|descripci|detalle|cuenta", t)), None
        )
        year_cols = {YEAR_RE.search(t).group(1): c for c, t in labels.items() if YEAR_RE.search(t) and c not in (code_col, name_col)}
        if len(year_cols) >= 1 and not any(re.search(r"saldo", t) for t in labels.values()):
            value_cols = year_cols
        else:
            preferred = [c for c, t in labels.items() if re.search(r"saldo\s*final|nuevo\s*saldo|saldo\s*actual", t)]
            generic = [c for c, t in labels.items() if re.search(r"saldo|valor|total", t) and not re.search(r"anterior|inicial", t)]
            single_value_col = (preferred or generic or [max(labels)])[0]
        break

    data_rows = rows[header_idx + 1 :] if header_idx is not None else rows
    if header_idx is None:
        # Sin encabezado: la columna de códigos es la que más valores tipo PUC tiene.
        counts: dict[int, int] = {}
        for _, cells in data_rows:
            for col, v in cells:
                if _is_code(v):
                    counts[col] = counts.get(col, 0) + 1
        if not counts or max(counts.values()) < 3:
            return [], warnings
        code_col = max(counts, key=counts.get)
        name_col = code_col + 1
        numeric_cols = [col for _, cells in data_rows for col, v in cells if col > code_col and parse_number(v) is not None]
        if not numeric_cols:
            return [], warnings
        single_value_col = max(numeric_cols)

    header_text = " ".join(row_text.get(r, "") for r, _ in rows[: (header_idx or 0) + 1])
    default_period = _detect_period(sheet_name, header_text, file_name)
    if not value_cols:
        if default_period is None:
            warnings.append(f"Hoja '{sheet_name}': no se pudo determinar el año del balance; se marca PERIODO_DESCONOCIDO.")
        value_cols = {default_period or "PERIODO_DESCONOCIDO": single_value_col}  # type: ignore[dict-item]

    result: list[TrialBalanceRow] = []
    for row_idx, cells in data_rows:
        cell_map = dict(cells)
        code = _is_code(cell_map.get(code_col))
        if code is None or row_idx not in row_text:
            continue
        name = cell_text(cell_map.get(name_col)) if name_col is not None else ""
        for period, col in value_cols.items():
            raw = cell_map.get(col)
            raw_text = cell_text(raw)
            value = parse_number(raw)
            if value is None and not raw_text:
                value = 0.0  # celda vacía = saldo cero
            result.append(
                TrialBalanceRow(
                    sheet=sheet_name,
                    row=row_idx,
                    period=period,
                    code=code,
                    name=name,
                    display_value=value,
                    raw_value_text=raw_text or "0",
                    cell_ref=f"{column_letter(col)}{row_idx}",
                    quote=row_text[row_idx],
                )
            )
    # Cuentas hoja: se descartan niveles agregados cuyo código es prefijo de otro código del mismo periodo.
    by_period: dict[str, set[str]] = {}
    for r in result:
        by_period.setdefault(r.period, set()).add(r.code)
    for r in result:
        codes = by_period[r.period]
        r.is_leaf = not any(other != r.code and other.startswith(r.code) for other in codes)
    unreadable = [r for r in result if r.display_value is None]
    if unreadable:
        warnings.append(f"Hoja '{sheet_name}': {len(unreadable)} celda(s) de saldo ilegibles (errores de Excel o texto).")
    return result, warnings


def _parse_tabular(sheets: Iterable[tuple[str, list[Row]]], document_id: str, display_name: str, file_format: str) -> ParsedDocument:
    pages: list[DocumentPage] = []
    tb_rows: list[TrialBalanceRow] = []
    warnings: list[str] = []
    for sheet_name, rows in sheets:
        if len(rows) > MAX_ROWS_PER_SHEET:
            warnings.append(f"Hoja '{sheet_name}' truncada a {MAX_ROWS_PER_SHEET} filas.")
            rows = rows[:MAX_ROWS_PER_SHEET]
        page, row_text = _sheet_to_page(sheet_name, rows)
        if not page.content:
            continue
        pages.append(page)
        extracted, sheet_warnings = extract_trial_balance(sheet_name, rows, row_text, display_name)
        tb_rows.extend(extracted)
        warnings.extend(sheet_warnings)
    text_sample = "\n".join(p.content[:3000] for p in pages)
    source = SourceDocument(
        document_id=document_id,
        document_name=display_name,
        document_type=guess_document_type(display_name, text_sample, file_format),
        file_format=file_format,  # type: ignore[arg-type]
        description=f"{'Libro Excel' if file_format == 'XLSX' else 'Archivo CSV'} con {len(pages)} hoja(s) con datos.",
        reported_units=guess_units(text_sample, file_format),
        pages=pages or [DocumentPage(page_or_sheet="Hoja1", content="")],
    )
    return ParsedDocument(source=source, trial_balance_rows=tb_rows, warnings=warnings)


def parse_xlsx(path: Path, document_id: str, display_name: str) -> ParsedDocument:
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=True, read_only=True)
    sheets: list[tuple[str, list[Row]]] = []
    try:
        for ws in workbook.worksheets:
            rows: list[Row] = []
            for row_idx, values in enumerate(ws.iter_rows(values_only=True), start=1):
                cells = [(col, v) for col, v in enumerate(values) if v is not None and str(v).strip() != ""]
                if cells:
                    rows.append((row_idx, cells))
            sheets.append((_nfc(ws.title), rows))
    finally:
        workbook.close()
    return _parse_tabular(sheets, document_id, display_name, "XLSX")


def _decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_csv(path: Path, document_id: str, display_name: str) -> ParsedDocument:
    text = _decode_csv(path.read_bytes())
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=";,\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if text.count(";") > text.count(",") else ","
    rows: list[Row] = []
    for row_idx, values in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
        cells = [(col, v.strip()) for col, v in enumerate(values) if v and v.strip()]
        if cells:
            rows.append((row_idx, cells))
    return _parse_tabular([(Path(display_name).stem, rows)], document_id, display_name, "CSV")


def parse_document(path: Path, document_id: str, display_name: Optional[str] = None) -> ParsedDocument:
    """Punto de entrada: elige el parser por extensión."""
    display_name = display_name or path.name
    file_format = SUPPORTED_EXTENSIONS.get(path.suffix.lower())
    if file_format is None:
        raise UnsupportedDocumentError(
            f"Formato no soportado: {path.suffix or 'sin extensión'} ({display_name}). Use PDF, XLSX o CSV."
        )
    if file_format == "PDF":
        return parse_pdf(path, document_id, display_name)
    if file_format == "XLSX":
        return parse_xlsx(path, document_id, display_name)
    return parse_csv(path, document_id, display_name)
