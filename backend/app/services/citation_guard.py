"""Guardián de trazabilidad: convierte afirmaciones del LLM en ``SourceCitation`` verificadas.

Un LLM puede alucinar citas. Antes de aceptar cualquier cita propuesta por un agente:
1. Se busca la cita en la página indicada (exacta y luego normalizando espacios/mayúsculas).
2. Si no aparece, se busca en las demás páginas del mismo documento y luego en todo el expediente.
3. La ``exact_quote`` guardada es SIEMPRE la subcadena literal del documento, no el texto del LLM.
Si la cita no se encuentra, la afirmación se descarta o queda marcada; nunca se inventa una fuente.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from app.schemas.deal import SourceCitation, SourceDocument

MIN_QUOTE_CHARS = 6


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Texto normalizado (NFC, casefold, espacios colapsados) y mapa índice normalizado -> índice original."""
    out_chars: list[str] = []
    index_map: list[int] = []
    previous_space = False
    for i, ch in enumerate(unicodedata.normalize("NFC", text)):
        if ch.isspace():
            if previous_space or not out_chars:
                continue
            out_chars.append(" ")
            index_map.append(i)
            previous_space = True
            continue
        for folded in ch.casefold():
            out_chars.append(folded)
            index_map.append(i)
        previous_space = False
    return "".join(out_chars), index_map


def find_literal(content: str, quote: str) -> Optional[str]:
    """Devuelve la subcadena literal de ``content`` que corresponde a ``quote`` (o None)."""
    quote = (quote or "").strip().strip('"“”«»')
    if len(quote) < MIN_QUOTE_CHARS:
        return None
    if quote in content:
        return quote
    content_nfc = unicodedata.normalize("NFC", content)
    norm_content, index_map = _normalize_with_map(content_nfc)
    norm_quote, _ = _normalize_with_map(quote)
    norm_quote = norm_quote.strip()
    if not norm_quote:
        return None
    pos = norm_content.find(norm_quote)
    if pos == -1:
        return None
    start = index_map[pos]
    end = index_map[pos + len(norm_quote) - 1] + 1
    literal = content_nfc[start:end]
    # El parser guarda el texto en NFC; si el contenido no lo estuviera, solo aceptamos subcadenas literales.
    return literal if literal in content else None


def line_ref_for(content: str, literal: str) -> str:
    idx = content.find(literal)
    line_no = content[:idx].count("\n") + 1 if idx >= 0 else 1
    line = content.splitlines()[line_no - 1] if content else ""
    if line.startswith("Fila "):
        row = line.split("|", 1)[0].replace("Fila", "").strip()
        return f"Fila {row}"
    return f"Línea {line_no}"


def citation_id_for(document_id: str, page: str, literal: str) -> str:
    digest = hashlib.sha1(f"{document_id}|{page}|{literal}".encode("utf-8")).hexdigest()[:12]
    return f"cit_{digest}"


def build_citation(
    document: SourceDocument,
    page: str,
    literal: str,
    confidence: float,
    cell_or_line_ref: Optional[str] = None,
    citation_id: Optional[str] = None,
) -> SourceCitation:
    content = next(p.content for p in document.pages if p.page_or_sheet == page)
    return SourceCitation(
        citation_id=citation_id or citation_id_for(document.document_id, page, literal),
        document_id=document.document_id,
        document_name=document.document_name,
        page_or_sheet=page,
        cell_or_line_ref=cell_or_line_ref or line_ref_for(content, literal),
        exact_quote=literal,
        confidence=max(0.0, min(1.0, confidence)),
    )


@dataclass(frozen=True)
class VerificationResult:
    citation: Optional[SourceCitation]
    relocated: bool  # True si la cita se encontró en otra página/documento distinto del indicado


def verify_quote(
    documents: Sequence[SourceDocument],
    document_id: Optional[str],
    page_or_sheet: Optional[str],
    quote: str,
    confidence: float = 0.85,
) -> VerificationResult:
    """Ubica literalmente una cita propuesta por un agente y devuelve una SourceCitation verificada."""
    by_id = {d.document_id: d for d in documents}

    def candidates() -> Iterable[tuple[SourceDocument, str, bool]]:
        doc = by_id.get(document_id or "")
        if doc is not None:
            for page in doc.pages:
                if page.page_or_sheet == page_or_sheet:
                    yield doc, page.page_or_sheet, False
            for page in doc.pages:
                if page.page_or_sheet != page_or_sheet:
                    yield doc, page.page_or_sheet, True
        for other in documents:
            if doc is not None and other.document_id == doc.document_id:
                continue
            for page in other.pages:
                yield other, page.page_or_sheet, True

    for doc, page, relocated in candidates():
        content = next(p.content for p in doc.pages if p.page_or_sheet == page)
        literal = find_literal(content, quote)
        if literal is not None:
            penalty = 0.1 if relocated else 0.0
            return VerificationResult(build_citation(doc, page, literal, confidence - penalty), relocated)
    return VerificationResult(None, False)
