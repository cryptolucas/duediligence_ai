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

SUPPORTED_EXTENSIONS = {
    ".pdf": "PDF",
    ".xlsx": "XLSX",
    ".xlsm": "XLSX",
    ".xls": "XLS",
    ".csv": "CSV",
    ".docx": "DOCX",
    ".txt": "TXT",
    ".md": "TXT",
}
TABULAR_FORMATS = {"XLSX", "XLS", "CSV"}
# Extensiones conocidas que no se pueden leer, con la indicación para el usuario.
_IMAGE_HINT = "Las fotos e imágenes no se pueden leer. Use el PDF digital del documento."
UNSUPPORTED_HINTS = {
    ".doc": "Guarde el documento de Word como .docx o expórtelo a PDF.",
    ".jpg": _IMAGE_HINT,
    ".jpeg": _IMAGE_HINT,
    ".png": _IMAGE_HINT,
    ".heic": _IMAGE_HINT,
    ".tif": _IMAGE_HINT,
    ".tiff": _IMAGE_HINT,
    ".zip": "Descomprima el archivo y cargue los documentos uno por uno.",
    ".rar": "Descomprima el archivo y cargue los documentos uno por uno.",
    ".pptx": "Exporte la presentación a PDF (Archivo → Exportar → PDF).",
    ".ppt": "Exporte la presentación a PDF (Archivo → Exportar → PDF).",
    ".ods": "Guarde la hoja de cálculo como .xlsx.",
    ".numbers": "Exporte la hoja de cálculo a .xlsx.",
    ".pages": "Exporte el documento a PDF o .docx.",
}
TEXT_PART_CHARS = 3500
MAX_ROWS_PER_SHEET = 10_000
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
CODE_RE = re.compile(r"^\d{1,10}$")


class UnsupportedDocumentError(ValueError):
    pass


class DocumentReadError(ValueError):
    """El archivo tiene una extensión soportada pero no se puede abrir (dañado, protegido, vacío)."""


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
    if file_format in TABULAR_FORMATS and re.search(r"balance\s*de\s*prueba|saldo\s*final|nuevo\s*saldo|auxiliar|bp_", haystack):
        return "TRIAL_BALANCE_XLSX"
    if re.search(r"existencia\s+y\s+representaci|c[áa]mara\s+de\s+comercio|matr[íi]cula\s+mercantil", haystack):
        return "CHAMBER_OF_COMMERCE_CERT"
    if "teaser" in haystack or "oportunidad de inversi" in haystack:
        return "TEASER"
    if re.search(r"aval[úu]o|canon de mercado", haystack):
        return "APPRAISAL"
    if re.search(r"estados?\s+financieros|situaci[óo]n\s+financiera|estado\s+de\s+resultados|notas?\s+a\s+los|revisor\s+fiscal|eeff", haystack):
        return "TRIAL_BALANCE_XLSX" if file_format in TABULAR_FORMATS else "FINANCIAL_STATEMENTS_PDF"
    if file_format in TABULAR_FORMATS:
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
            if pdf.needs_pass:
                raise DocumentReadError(
                    f"{display_name} está protegido con contraseña. Ábralo, use Imprimir → Guardar como PDF (sin "
                    "contraseña) y vuelva a cargarlo."
                )
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


TABULAR_LABELS = {"XLSX": "Libro Excel", "XLS": "Libro Excel (.xls)"}


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
        description=f"{TABULAR_LABELS.get(file_format, 'Archivo CSV')} con {len(pages)} hoja(s) con datos.",
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


def parse_xls(path: Path, document_id: str, display_name: str) -> ParsedDocument:
    """Excel 97-2003 (.xls), formato que aún exportan World Office, Helisa y otros programas contables."""
    import xlrd

    book = xlrd.open_workbook(str(path), on_demand=True)
    sheets: list[tuple[str, list[Row]]] = []
    try:
        for sheet in book.sheets():
            rows: list[Row] = []
            for r in range(min(sheet.nrows, MAX_ROWS_PER_SHEET + 1)):
                cells: list[tuple[int, object]] = []
                for c in range(sheet.ncols):
                    cell = sheet.cell(r, c)
                    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        continue
                    value: object = "#ERROR" if cell.ctype == xlrd.XL_CELL_ERROR else cell.value
                    if isinstance(value, str) and not value.strip():
                        continue
                    cells.append((c, value))
                if cells:
                    rows.append((r + 1, cells))
            sheets.append((_nfc(sheet.name), rows))
    finally:
        book.release_resources()
    return _parse_tabular(sheets, document_id, display_name, "XLS")


def _text_pages(lines: Iterable[str]) -> list[DocumentPage]:
    """Agrupa renglones de texto en partes de ~TEXT_PART_CHARS caracteres (documentos sin paginación)."""
    pages: list[DocumentPage] = []
    current: list[str] = []
    size = 0
    for line in lines:
        line = _nfc(line).strip()
        if not line:
            continue
        if current and size + len(line) > TEXT_PART_CHARS:
            pages.append(DocumentPage(page_or_sheet=f"Parte {len(pages) + 1}", content="\n".join(current)))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        pages.append(DocumentPage(page_or_sheet=f"Parte {len(pages) + 1}", content="\n".join(current)))
    return pages


def _text_document(lines: Iterable[str], document_id: str, display_name: str, file_format: str, kind: str) -> ParsedDocument:
    pages = _text_pages(lines)
    text_sample = "\n".join(p.content for p in pages[:6])
    source = SourceDocument(
        document_id=document_id,
        document_name=display_name,
        document_type=guess_document_type(display_name, text_sample, file_format),
        file_format=file_format,  # type: ignore[arg-type]
        description=f"{kind} con {len(pages)} parte(s) de texto.",
        reported_units=guess_units(text_sample, file_format),
        pages=pages or [DocumentPage(page_or_sheet="Parte 1", content="")],
    )
    return ParsedDocument(source=source)


def parse_docx(path: Path, document_id: str, display_name: str) -> ParsedDocument:
    """Word (.docx): párrafos y tablas en orden de aparición; las celdas de una fila se unen con ' | '."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(Paragraph(child, document).text)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                cells: list[str] = []
                for cell in row.cells:
                    text = " ".join(cell.text.split())
                    if text and (not cells or cells[-1] != text):  # las celdas combinadas se repiten
                        cells.append(text.replace("|", "/"))
                if cells:
                    lines.append(" | ".join(cells))
    return _text_document(lines, document_id, display_name, "DOCX", "Documento Word")


def parse_txt(path: Path, document_id: str, display_name: str) -> ParsedDocument:
    return _text_document(_decode_csv(path.read_bytes()).splitlines(), document_id, display_name, "TXT", "Archivo de texto")


_READ_ERROR_HINTS = {
    "PDF": "El PDF está dañado o no es un PDF real. Si abre bien en su computador, use Imprimir → Guardar como PDF y vuelva a cargarlo.",
    "XLSX": (
        "El archivo Excel está dañado, protegido con contraseña o no es un .xlsx real (¿se cambió la extensión?). "
        "Ábralo en Excel, quite la contraseña si la tiene y guárdelo de nuevo como .xlsx."
    ),
    "XLS": "El archivo .xls está dañado o protegido. Ábralo en Excel y guárdelo como .xlsx.",
    "CSV": "No se pudo leer el CSV. Ábralo en Excel y guárdelo de nuevo como .xlsx o CSV UTF-8.",
    "DOCX": "El documento de Word está dañado o protegido. Ábralo en Word y guárdelo de nuevo como .docx o expórtelo a PDF.",
    "TXT": "No se pudo leer el archivo de texto.",
}


def parse_document(path: Path, document_id: str, display_name: Optional[str] = None) -> ParsedDocument:
    """Punto de entrada: elige el parser por extensión.

    Lanza ``UnsupportedDocumentError`` (extensión no admitida) o ``DocumentReadError`` (archivo vacío, dañado o
    protegido) con un mensaje que explica al usuario cómo solucionarlo.
    """
    display_name = display_name or path.name
    suffix = path.suffix.lower()
    file_format = SUPPORTED_EXTENSIONS.get(suffix)
    if file_format is None:
        hint = UNSUPPORTED_HINTS.get(suffix, "Use PDF, Excel (XLSX/XLS), CSV, Word (DOCX) o TXT.")
        raise UnsupportedDocumentError(f"Formato no soportado: {suffix or 'sin extensión'} ({display_name}). {hint}")
    if path.stat().st_size == 0:
        raise DocumentReadError(f"{display_name} está vacío (0 bytes). Vuelva a descargarlo o exportarlo y cárguelo de nuevo.")
    parsers = {"PDF": parse_pdf, "XLSX": parse_xlsx, "XLS": parse_xls, "CSV": parse_csv, "DOCX": parse_docx, "TXT": parse_txt}
    try:
        return parsers[file_format](path, document_id, display_name)
    except (DocumentReadError, UnsupportedDocumentError):
        raise
    except Exception as exc:  # noqa: BLE001 - cada librería lanza sus propios errores
        raise DocumentReadError(f"No se pudo abrir {display_name}. {_READ_ERROR_HINTS[file_format]}") from exc
