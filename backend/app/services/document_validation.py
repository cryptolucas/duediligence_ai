"""Casillas de carga y validación de documentos — 100 % determinista.

El análisis necesita tres documentos obligatorios, cada uno con su casilla:

* TRIAL_BALANCE ......... Balance de prueba (Excel/CSV): la fuente de TODAS las cifras del motor financiero.
* FINANCIAL_STATEMENTS .. Estados financieros con notas (PDF): ajustes al EBITDA, deudas, litigios, partes relacionadas.
* CHAMBER_CERTIFICATE ... Certificado de existencia y representación legal (PDF): identidad, NIT y CIIU (múltiplos).

«Otros archivos» (OTHER) es opcional: contexto complementario que nunca alimenta el motor.

Cada archivo se valida al cargarlo (``POST /api/documents/validate``) y de nuevo al generar el expediente, con
mensajes que dicen qué está mal y cómo solucionarlo.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from app.agents.context import RELEVANCE_KEYWORDS
from app.schemas.api import DocumentValidation, UploadSlotSpec, ValidationIssue
from app.services.document_parser import (
    SUPPORTED_EXTENSIONS,
    UNSUPPORTED_HINTS,
    DocumentReadError,
    ParsedDocument,
    UnsupportedDocumentError,
    parse_document,
)

MAX_FILE_MB = 25

SLOT_SPECS: tuple[UploadSlotSpec, ...] = (
    UploadSlotSpec(
        id="TRIAL_BALANCE",
        number=1,
        label="Balance de prueba",
        required=True,
        max_files=3,
        accepted_extensions=[".xlsx", ".xls", ".xlsm", ".csv"],
        what_to_upload=(
            "Exportación del balance de prueba desde el software contable (Siigo, World Office, Helisa, Alegra, SAP…) "
            "con el detalle de cuentas del PUC."
        ),
        must_contain=[
            "Código de cuenta PUC (ej. 1105, 4135, 5105) y nombre de la cuenta.",
            "Saldo final de cada cuenta (columna «Saldo final», «Nuevo saldo» o una columna por año).",
            "Cuentas de las clases 1 a 6: activos, pasivos, patrimonio, ingresos, gastos y costos (antes del cierre contable).",
            "El año del cierre en el nombre de la hoja, en el encabezado o en el nombre del archivo (ej. BP_2025).",
            "Ideal: los últimos 3 cierres anuales (un archivo por año, una hoja por año o una columna por año).",
        ],
        examples=["Balance_Prueba_2023-2025.xlsx", "BP_2025.xls", "balance_prueba_2024.csv"],
        why_it_matters="Es la fuente de todas las cifras: ingresos, EBITDA, deuda, capital de trabajo y valoración se calculan a partir de este archivo.",
    ),
    UploadSlotSpec(
        id="FINANCIAL_STATEMENTS",
        number=2,
        label="Estados financieros con notas",
        required=True,
        max_files=3,
        accepted_extensions=[".pdf"],
        what_to_upload=(
            "Estados financieros certificados o dictaminados (NIIF para PYMES) del último cierre, con sus notas y, si lo hay, "
            "el dictamen del revisor fiscal."
        ),
        must_contain=[
            "Estado de situación financiera (balance general) y estado de resultados.",
            "Notas a los estados financieros: partes relacionadas, obligaciones financieras, litigios, impuestos.",
            "PDF digital (con texto seleccionable), no escaneado ni fotografiado.",
        ],
        examples=["EEFF_2025_con_notas.pdf", "Estados_Financieros_Dictaminados_2024.pdf"],
        why_it_matters="Las notas permiten proponer ajustes al EBITDA y detectar deudas, litigios y operaciones con los socios.",
    ),
    UploadSlotSpec(
        id="CHAMBER_CERTIFICATE",
        number=3,
        label="Certificado de existencia y representación legal",
        required=True,
        max_files=1,
        accepted_extensions=[".pdf"],
        what_to_upload="Certificado de la Cámara de Comercio (o del RUES) descargado en PDF, idealmente con menos de 30 días de expedido.",
        must_contain=[
            "Razón social, NIT y actividad económica (código CIIU).",
            "Representante legal, suplente y sus facultades o límites.",
        ],
        examples=["Certificado_Camara_Comercio_2025.pdf"],
        why_it_matters="Identifica la empresa y su sector (CIIU), que define los múltiplos de valoración y los benchmarks.",
    ),
    UploadSlotSpec(
        id="OTHER",
        number=4,
        label="Otros archivos (opcionales)",
        required=False,
        max_files=10,
        accepted_extensions=[".pdf", ".docx", ".xlsx", ".xls", ".xlsm", ".csv", ".txt", ".md"],
        what_to_upload=(
            "Cualquier documento adicional que ayude a entender mejor la empresa y que considere útil para un análisis más "
            "completo y preciso."
        ),
        must_contain=[
            "Ejemplos: teaser o presentación de la empresa, avalúos, contratos de crédito o de arriendo, cartera por edades, "
            "principales clientes, declaraciones de renta, actas de asamblea, proyecciones o informes de gestión.",
            "Documentos digitales (con texto), en español o inglés.",
        ],
        examples=["Teaser_Proyecto.pdf", "Avaluo_Bodega.pdf", "Cartera_por_edades.xlsx", "Contrato_credito.docx"],
        why_it_matters=(
            "Se leen y se usan como contexto complementario para enriquecer ajustes, riesgos y el memo. Nunca reemplazan las "
            "cifras de los documentos obligatorios: lo que se proponga a partir de ellos queda pendiente de su revisión, y "
            "las páginas sin información útil se descartan."
        ),
    ),
)
SPECS_BY_ID = {spec.id: spec for spec in SLOT_SPECS}
REQUIRED_SLOTS = tuple(spec.id for spec in SLOT_SPECS if spec.required)

CERT_TITLE_RE = re.compile(r"existencia\s+y\s+representaci[óo]n\s+legal", re.IGNORECASE)
CERT_RE = re.compile(r"c[áa]mara\s+de\s+comercio|registro\s+[úu]nico\s+empresarial|\brues\b", re.IGNORECASE)
CERT_STRONG_RE = re.compile(
    r"existencia\s+y\s+representaci|certificado\s+de\s+existencia|matr[íi]cula\s+mercantil|certifica\s*:", re.IGNORECASE
)
STATEMENT_RE = re.compile(
    r"estado\s+de\s+situaci[óo]n\s+financiera|balance\s+general|estado\s+de\s+resultados|estado\s+de\s+resultado\s+integral",
    re.IGNORECASE,
)
NOTES_RE = re.compile(r"notas?\s+(?:a|de)\s+(?:los\s+)?estados\s+financieros|\bnota\s+\d{1,2}\b", re.IGNORECASE)
NIT_RE = re.compile(r"\bNIT\b\.?\s*(?:No\.?|n[úu]mero)?\s*:?\s*(\d{3}\.?\d{3}\.?\d{3}\s*-\s*\d)", re.IGNORECASE)
NAME_RE = re.compile(r"(?:raz[óo]n\s+social|nombre)\s*:\s*(.+)", re.IGNORECASE)
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
EXPEDITION_NUMERIC_RE = re.compile(r"expedici[óo]n\D{0,30}?(\d{1,2})[/-](\d{1,2})[/-](\d{4})", re.IGNORECASE)
EXPEDITION_TEXT_RE = re.compile(r"expedici[óo]n\D{0,30}?(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.IGNORECASE)
CERT_MAX_AGE_DAYS = 30
FORMAT_LABEL = {"PDF": "PDF", "XLSX": "Excel", "XLS": "Excel (.xls)", "CSV": "CSV", "DOCX": "Word", "TXT": "texto"}


def slot_spec(slot: str) -> UploadSlotSpec:
    if slot not in SPECS_BY_ID:
        raise ValueError(f"Casilla desconocida: {slot}. Use una de: {', '.join(SPECS_BY_ID)}.")
    return SPECS_BY_ID[slot]


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _full_text(parsed: ParsedDocument, max_pages: Optional[int] = None) -> str:
    pages = parsed.source.pages if max_pages is None else parsed.source.pages[:max_pages]
    return "\n".join(p.content for p in pages)


def _value_rows(parsed: ParsedDocument):
    return [r for r in parsed.trial_balance_rows if r.is_leaf and r.display_value]


def detect_slot(parsed: ParsedDocument) -> Optional[str]:
    """Casilla a la que parece pertenecer el documento según su contenido (None = no es un obligatorio)."""
    if len(_value_rows(parsed)) >= 5:
        return "TRIAL_BALANCE"
    if parsed.source.file_format not in ("PDF", "DOCX", "TXT"):
        return None
    head = _full_text(parsed, 3)
    statements = len(STATEMENT_RE.findall(_full_text(parsed)))
    is_cert = bool(CERT_TITLE_RE.search(head) or (CERT_RE.search(head) and CERT_STRONG_RE.search(head)))
    if is_cert and statements == 0:
        return "CHAMBER_CERTIFICATE"
    if statements >= 1 and parsed.source.file_format == "PDF":
        return "FINANCIAL_STATEMENTS"
    return "CHAMBER_CERTIFICATE" if is_cert else None


def _expedition_date(text: str) -> Optional[date]:
    plain = _plain(text)
    match = EXPEDITION_NUMERIC_RE.search(plain)
    try:
        if match:
            day, month, year = (int(g) for g in match.groups())
            return date(year, month, day)
        match = EXPEDITION_TEXT_RE.search(plain)
        if match and match.group(2).lower() in MONTHS:
            return date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1)))
    except ValueError:
        return None
    return None


def company_from_certificate(parsed: ParsedDocument) -> tuple[Optional[str], Optional[str]]:
    """(razón social, NIT) leídos del certificado, si aparecen."""
    name = nit = None
    for line in _full_text(parsed, 3).splitlines():
        if nit is None and (m := NIT_RE.search(line)):
            nit = re.sub(r"\s+", "", m.group(1))
        if name is None and (m := NAME_RE.search(line)):
            name = m.group(1).split("|")[0].strip() or None
    return name, nit


def _scanned_issue(parsed: ParsedDocument) -> Optional[ValidationIssue]:
    if not parsed.scanned_pages:
        return None
    pages = parsed.scanned_pages
    listed = ", ".join(pages[:6]) + ("…" if len(pages) > 6 else "")
    return ValidationIssue(
        level="warning",
        message=f"{len(pages)} página(s) escaneadas sin texto ({listed}): su contenido no se podrá leer.",
        fix="Si esas páginas tienen información importante, solicite la versión digital del documento.",
    )


def _no_text_issue() -> ValidationIssue:
    return ValidationIssue(
        level="error",
        message="El documento no tiene texto legible: parece escaneado o es una imagen.",
        fix="Solicite la versión digital (exportada desde el software contable, Word o la página de la Cámara de Comercio). Los escaneos y fotos no se pueden leer.",
    )


def _wrong_slot_issue(detected: str, current: str) -> ValidationIssue:
    target = SPECS_BY_ID[detected]
    return ValidationIssue(
        level="error",
        message=f"Este archivo parece ser «{target.label}», no «{SPECS_BY_ID[current].label}».",
        fix=f"Cárguelo en la casilla {target.number} ({target.label}) y suba aquí el documento que corresponde.",
    )


# ---------------------------------------------------------------------------
# Reglas por casilla
# ---------------------------------------------------------------------------


def _check_trial_balance(parsed: ParsedDocument, issues: list[ValidationIssue]) -> tuple[str, list[str]]:
    rows = parsed.trial_balance_rows
    values = _value_rows(parsed)
    periods = sorted({r.period for r in rows})
    if not rows:
        detected = detect_slot(parsed)
        if detected and detected != "TRIAL_BALANCE":
            issues.append(_wrong_slot_issue(detected, "TRIAL_BALANCE"))
        issues.append(
            ValidationIssue(
                level="error",
                message="No encontramos cuentas contables en el archivo.",
                fix=(
                    "El archivo debe tener una columna con el código de cuenta PUC (ej. 1105, 4135) y otra con el saldo final. "
                    "Expórtelo desde el software contable como «Balance de prueba» en Excel."
                ),
            )
        )
        return "Sin cuentas PUC", []
    if len(values) < 5:
        issues.append(
            ValidationIssue(
                level="error",
                message=f"Solo encontramos {len(values)} cuenta(s) con saldo distinto de cero.",
                fix=(
                    "Verifique que la columna de saldo final tenga valores. Si el archivo usa fórmulas, ábralo en Excel y guárdelo "
                    "de nuevo (o copie y pegue como valores) antes de cargarlo."
                ),
            )
        )
    if "PERIODO_DESCONOCIDO" in periods:
        issues.append(
            ValidationIssue(
                level="error",
                message="No pudimos identificar el año del balance.",
                fix=(
                    "Incluya el año en el nombre de la hoja (ej. BP_2025), en el encabezado (ej. «Balance de prueba a 31 de "
                    "diciembre de 2025») o en el nombre del archivo (ej. Balance_2025.xlsx)."
                ),
            )
        )
    classes = {r.code[0] for r in values}
    if values and not ({"1", "4"} & classes):
        issues.append(
            ValidationIssue(
                level="error",
                message="No parece un balance de prueba del PUC colombiano: no hay cuentas de activo (clase 1) ni de ingresos (clase 4).",
                fix="Cargue el balance de prueba con todas las cuentas (clases 1 a 6). Otros reportes van en «Otros archivos».",
            )
        )
    elif values and "4" not in classes:
        issues.append(
            ValidationIssue(
                level="warning",
                message="No hay cuentas de ingresos (clase 4) con saldo: parece un balance después del cierre contable.",
                fix="Sin ingresos no se calculan márgenes ni EBITDA. Exporte el balance de prueba antes del cierre, con las cuentas de resultados.",
            )
        )
    elif values and "1" not in classes:
        issues.append(
            ValidationIssue(
                level="warning",
                message="No hay cuentas de activo (clase 1): solo se podrá analizar el estado de resultados.",
                fix="Exporte el balance de prueba completo (clases 1 a 6).",
            )
        )
    real_periods = [p for p in periods if p != "PERIODO_DESCONOCIDO"]
    if len(real_periods) == 1:
        issues.append(
            ValidationIssue(
                level="warning",
                message=f"Solo se detectó el año {real_periods[0]}: no se podrán calcular crecimientos ni tendencias.",
                fix="Si tiene los cierres de los dos años anteriores, cárguelos también (en este archivo o en archivos adicionales de esta casilla).",
            )
        )
    unreadable = sum(1 for r in rows if r.display_value is None)
    if unreadable:
        issues.append(
            ValidationIssue(
                level="warning",
                message=f"{unreadable} celda(s) de saldo no se pudieron leer (errores de Excel como #REF! o texto): esas cuentas se excluirán.",
                fix="Corrija esas celdas en el archivo original si son importantes.",
            )
        )
    summary = f"{len(values)} cuentas con saldo · {'periodos ' + ', '.join(real_periods) if real_periods else 'sin año'} · cifras en {parsed.source.reported_units}"
    return summary, real_periods


def _check_financial_statements(parsed: ParsedDocument, issues: list[ValidationIssue]) -> tuple[str, list[str]]:
    text = _full_text(parsed)
    if not text.strip():
        issues.append(_no_text_issue())
        return "Sin texto", []
    detected = detect_slot(parsed)
    if detected == "CHAMBER_CERTIFICATE":
        issues.append(_wrong_slot_issue(detected, "FINANCIAL_STATEMENTS"))
        return "Certificado de Cámara de Comercio", []
    if not STATEMENT_RE.search(text):
        issues.append(
            ValidationIssue(
                level="error",
                message="No encontramos un estado de situación financiera ni un estado de resultados en este PDF.",
                fix=(
                    "Verifique que sea el documento correcto: debe incluir el balance general (estado de situación financiera) y el "
                    "estado de resultados. Si es otro tipo de documento, cárguelo en «Otros archivos»."
                ),
            )
        )
    if not NOTES_RE.search(text):
        issues.append(
            ValidationIssue(
                level="warning",
                message="No encontramos las notas a los estados financieros.",
                fix="Sin notas no se pueden proponer ajustes al EBITDA ni detectar litigios u operaciones con socios. Si las tiene en otro PDF, cárguelo también en esta casilla.",
            )
        )
    years = sorted({y for page in parsed.source.pages if STATEMENT_RE.search(page.content) for y in YEAR_RE.findall(page.content)})
    pages = len(parsed.source.pages)
    summary = f"{pages} página(s)" + (f" · años {', '.join(years[-4:])}" if years else "") + f" · cifras en {parsed.source.reported_units}"
    return summary, years[-4:]


def _check_certificate(parsed: ParsedDocument, issues: list[ValidationIssue], today: date) -> tuple[str, list[str]]:
    text = _full_text(parsed)
    if not text.strip():
        issues.append(_no_text_issue())
        return "Sin texto", []
    detected = detect_slot(parsed)
    if detected != "CHAMBER_CERTIFICATE":
        if detected == "FINANCIAL_STATEMENTS":
            issues.append(_wrong_slot_issue(detected, "CHAMBER_CERTIFICATE"))
        else:
            issues.append(
                ValidationIssue(
                    level="error",
                    message="Este PDF no parece un certificado de existencia y representación legal.",
                    fix=(
                        "Descárguelo de la Cámara de Comercio (o del RUES) en PDF y cárguelo aquí. Otros documentos societarios "
                        "(estatutos, actas) van en «Otros archivos»."
                    ),
                )
            )
        return "No es un certificado", []
    name, nit = company_from_certificate(parsed)
    if nit is None:
        issues.append(
            ValidationIssue(
                level="warning",
                message="No pudimos leer el NIT en el certificado.",
                fix="Verifique que sea el certificado completo. Si continúa, escriba el NIT en «Datos de la empresa».",
            )
        )
    issued = _expedition_date(text)
    if issued is not None and (today - issued).days > CERT_MAX_AGE_DAYS:
        issues.append(
            ValidationIssue(
                level="warning",
                message=f"El certificado fue expedido el {issued.strftime('%d/%m/%Y')} (hace {(today - issued).days} días).",
                fix="Para el Comité se recomienda un certificado con menos de 30 días. Puede continuar con este y actualizarlo después.",
            )
        )
    parts = [p for p in (name and f"Razón social: {name[:80]}", nit and f"NIT {nit}", issued and f"expedido {issued.strftime('%d/%m/%Y')}") if p]
    return " · ".join(parts) or f"{len(parsed.source.pages)} página(s)", []


def _check_other(parsed: ParsedDocument, issues: list[ValidationIssue]) -> tuple[str, list[str], Optional[str]]:
    pages = [p for p in parsed.source.pages if p.content.strip()]
    if not pages and not parsed.trial_balance_rows:
        issues.append(
            ValidationIssue(
                level="error",
                message="No encontramos texto legible en el archivo (está vacío, escaneado o es una imagen).",
                fix="Cargue la versión digital o quite el archivo: los «Otros archivos» son opcionales.",
            )
        )
        return "Sin texto", [], None
    detected = detect_slot(parsed)
    if detected is not None:
        target = SPECS_BY_ID[detected]
        issues.append(
            ValidationIssue(
                level="warning",
                message=f"Parece ser «{target.label}». En «Otros archivos» solo se usa como contexto: sus cifras no entran al motor financiero.",
                fix=f"Si es uno de los documentos principales, muévalo a la casilla {target.number}.",
            )
        )
    relevant = sum(1 for p in pages if RELEVANCE_KEYWORDS.search(p.content))
    if pages and relevant == 0:
        issues.append(
            ValidationIssue(
                level="warning",
                message="No encontramos información financiera, legal o comercial en este documento: probablemente no aporte al análisis.",
                fix="Puede dejarlo o quitarlo; si no es relevante, el sistema lo ignorará.",
            )
        )
    unit = "hoja(s)" if parsed.source.file_format in ("XLSX", "XLS", "CSV") else "página(s)" if parsed.source.file_format == "PDF" else "parte(s)"
    summary = f"{FORMAT_LABEL.get(parsed.source.file_format, parsed.source.file_format)} · {len(pages)} {unit} · {relevant} con información útil"
    return summary, [], detected


def validate_parsed(parsed: ParsedDocument, slot: str, file_name: str, today: Optional[date] = None) -> DocumentValidation:
    spec = slot_spec(slot)
    issues: list[ValidationIssue] = []
    suggested: Optional[str] = None
    if slot == "TRIAL_BALANCE":
        summary, periods = _check_trial_balance(parsed, issues)
    elif slot == "FINANCIAL_STATEMENTS":
        summary, periods = _check_financial_statements(parsed, issues)
    elif slot == "CHAMBER_CERTIFICATE":
        summary, periods = _check_certificate(parsed, issues, today or date.today())
    else:
        summary, periods, suggested = _check_other(parsed, issues)
    if slot != "OTHER":
        detected = detect_slot(parsed)
        if any(i.level == "error" for i in issues):
            suggested = detected if detected and detected != slot else "OTHER"
    scanned = _scanned_issue(parsed)
    if scanned is not None and not any(i.message.startswith("El documento no tiene texto") for i in issues):
        issues.append(scanned)
    status = "error" if any(i.level == "error" for i in issues) else "warning" if issues else "valid"
    return DocumentValidation(
        file_name=file_name,
        slot=spec.id,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        periods=periods,
        issues=issues,
        suggested_slot=suggested if suggested != slot else None,
    )


def check_extension(file_name: str, slot: str) -> Optional[ValidationIssue]:
    spec = slot_spec(slot)
    suffix = Path(file_name).suffix.lower()
    if suffix in spec.accepted_extensions:
        return None
    accepted = ", ".join(e.lstrip(".").upper() for e in spec.accepted_extensions)
    if suffix in SUPPORTED_EXTENSIONS and slot != "OTHER":
        fix = f"Esta casilla solo admite {accepted}. Si el documento es complementario, cárguelo en «Otros archivos»."
        if slot == "TRIAL_BALANCE" and suffix == ".pdf":
            fix = "Exporte el balance de prueba desde el software contable en Excel (XLSX/XLS) o CSV; el PDF no permite leer las cuentas con precisión."
        if slot in ("FINANCIAL_STATEMENTS", "CHAMBER_CERTIFICATE") and suffix != ".pdf":
            fix = "Cargue el documento en PDF (Archivo → Guardar como / Exportar → PDF)."
    else:
        fix = f"{UNSUPPORTED_HINTS.get(suffix, '')} Formatos aceptados en esta casilla: {accepted}.".strip()
    return ValidationIssue(level="error", message=f"Formato no admitido en «{spec.label}»: {suffix or 'sin extensión'}.", fix=fix)


def _slot_for_misplaced(path: Path, file_name: str, current: str) -> Optional[str]:
    """Para un archivo con formato de otra casilla: lo lee y sugiere dónde va (para el botón «Mover a…»)."""
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS or path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        return None
    try:
        detected = detect_slot(parse_document(path, "doc_sugerencia", file_name)) or "OTHER"
    except (UnsupportedDocumentError, DocumentReadError):
        return None
    candidates = [detected, "OTHER"]
    return next((s for s in candidates if s != current and suffix in SPECS_BY_ID[s].accepted_extensions), None)


def validate_file(
    path: Path, slot: Optional[str], file_name: str, document_id: str, today: Optional[date] = None
) -> tuple[DocumentValidation, Optional[ParsedDocument]]:
    """Lee y valida un archivo. ``slot=None`` = clasificación automática (API anterior a las casillas)."""
    target_slot = slot or "OTHER"
    if slot is not None:
        bad_ext = check_extension(file_name, slot)
        if bad_ext is not None:
            return (
                DocumentValidation(
                    file_name=file_name,
                    slot=slot,
                    status="error",
                    summary="Formato no admitido",
                    issues=[bad_ext],
                    suggested_slot=_slot_for_misplaced(path, file_name, slot),
                ),
                None,
            )
    size = path.stat().st_size
    if size > MAX_FILE_MB * 1024 * 1024:
        issue = ValidationIssue(
            level="error",
            message=f"El archivo pesa {size / 1024 / 1024:.1f} MB y el máximo es {MAX_FILE_MB} MB.",
            fix="Comprima el PDF (por ejemplo, Imprimir → Guardar como PDF) o divídalo en partes.",
        )
        return DocumentValidation(file_name=file_name, slot=target_slot, status="error", summary="Archivo muy grande", issues=[issue]), None
    try:
        parsed = parse_document(path, document_id, file_name)
    except (UnsupportedDocumentError, DocumentReadError) as exc:
        issue = ValidationIssue(level="error", message=str(exc), fix=None)
        return DocumentValidation(file_name=file_name, slot=target_slot, status="error", summary="No se pudo leer", issues=[issue]), None
    if slot is None:
        target_slot = detect_slot(parsed) or "OTHER"
    return validate_parsed(parsed, target_slot, file_name, today), parsed


def missing_required(slots_with_valid_files: Iterable[str]) -> list[UploadSlotSpec]:
    present = set(slots_with_valid_files)
    return [SPECS_BY_ID[s] for s in REQUIRED_SLOTS if s not in present]


PRIMARY_TYPES_BY_SLOT = {
    "TRIAL_BALANCE": "TRIAL_BALANCE_XLSX",
    "FINANCIAL_STATEMENTS": "FINANCIAL_STATEMENTS_PDF",
    "CHAMBER_CERTIFICATE": "CHAMBER_OF_COMMERCE_CERT",
}


def assign_slot(parsed: ParsedDocument, slot: str) -> ParsedDocument:
    """Fija el rol del documento según la casilla en la que el usuario lo cargó.

    * Casillas obligatorias: el tipo documental queda fijado por la casilla (no por adivinanza de palabras clave).
    * «Otros archivos»: nunca es fuente autoritativa ni alimenta el motor; si parece un documento principal se
      trata como "OTHER" y se descartan sus filas de balance de prueba.
    """
    source = parsed.source.model_copy(update={"upload_slot": slot})
    if slot in PRIMARY_TYPES_BY_SLOT:
        source = source.model_copy(update={"document_type": PRIMARY_TYPES_BY_SLOT[slot]})
        rows = parsed.trial_balance_rows if slot == "TRIAL_BALANCE" else []
    else:
        if source.document_type in PRIMARY_TYPES_BY_SLOT.values():
            source = source.model_copy(update={"document_type": "OTHER"})
        rows = []
    return parsed.model_copy(update={"source": source, "trial_balance_rows": rows})
