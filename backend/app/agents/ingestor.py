"""Nodo 1 — Agente de Ingesta y Normalización PUC.

Flujo:
1. Balances de prueba (XLSX/CSV): filas estructuradas por el parser -> cuentas hoja -> regla PUC
   -> (opcional) revisión del LLM sobre la categoría -> signo normalizado de forma determinista.
2. Periodos sin balance de prueba: si hay LLM, clasifica líneas de los EEFF en PDF; el valor se lee
   del texto de la línea con el parser numérico (el LLM solo elige la columna y la categoría).
3. Lo que no se puede leer con certeza va a ``unreadable_or_unmapped_items`` con su cita.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional, Sequence

from app.agents.context import AgentRuntime, NodeTimer, units_multiplier
from app.agents.llm_schemas import AccountMappingResponse, StatementMappingResponse
from app.agents.prompts import INGESTOR_ACCOUNTS, INGESTOR_STATEMENTS
from app.schemas.deal import MappedAccountItem, SourceDocument, UnreadableItem
from app.services.citation_guard import build_citation
from app.services.document_parser import ParsedDocument, TrialBalanceRow
from app.services.llm_client import LLMError
from app.services.numbers import find_numbers
from app.services.puc_mapper import (
    detect_sign_convention,
    is_pre_closing,
    rule_based_mapping,
    sign_note,
    to_engine_value,
)

LLM_BATCH_SIZE = 120
STATEMENT_PAGE_RE = re.compile(
    r"estado\s+de\s+situaci[óo]n\s+financiera|balance\s+general|estado\s+de\s+resultados", re.IGNORECASE
)
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


class IngestionError(ValueError):
    """No se encontró ninguna cifra financiera legible en los documentos."""


def _llm_review_categories(
    rows: Sequence[TrialBalanceRow], runtime: AgentRuntime, log_notes: list[str]
) -> dict[str, tuple[str, str, float]]:
    """Pide al LLM revisar la categoría de cada cuenta. Devuelve {row_key: (categoría, rationale, confianza)}."""
    if not runtime.uses_llm or not rows:
        return {}
    reviewed: dict[str, tuple[str, str, float]] = {}
    for start in range(0, len(rows), LLM_BATCH_SIZE):
        batch = rows[start : start + LLM_BATCH_SIZE]
        listing = "\n".join(
            f"- row_id={r.sheet}:{r.row}:{r.period} | código {r.code} | {r.name} | sugerencia regla: "
            f"{rule_based_mapping(r.code, r.name).category}"
            for r in batch
        )
        try:
            response = runtime.llm.complete_json(  # type: ignore[union-attr]
                INGESTOR_ACCOUNTS,
                f"Cuentas a clasificar:\n{listing}",
                AccountMappingResponse,
                deal_id=runtime.deal_id,
                task="ingestor.accounts",
            )
        except LLMError as exc:
            log_notes.append(f"LLM no disponible para clasificar cuentas ({exc}); se usan reglas PUC.")
            return reviewed
        for item in response.items:
            reviewed[item.row_id] = (item.standard_category, item.rationale, item.confidence)
    return reviewed


def map_trial_balances(
    parsed: Sequence[ParsedDocument], runtime: AgentRuntime, log_notes: list[str]
) -> tuple[list[MappedAccountItem], list[UnreadableItem], list[str], set[str]]:
    accounts: list[MappedAccountItem] = []
    unreadable: list[UnreadableItem] = []
    pre_closing: list[str] = []
    covered_periods: set[str] = set()

    # Un solo origen por periodo: el primer documento/hoja que lo trae (evita doble conteo).
    groups: dict[str, tuple[ParsedDocument, str, list[TrialBalanceRow]]] = {}
    for doc in parsed:
        by_key: dict[tuple[str, str], list[TrialBalanceRow]] = defaultdict(list)
        for row in doc.trial_balance_rows:
            by_key[(row.period, row.sheet)].append(row)
        for (period, sheet), rows in by_key.items():
            if period in groups:
                log_notes.append(
                    f"Periodo {period} repetido en {doc.source.document_name}/{sheet}; se conserva "
                    f"{groups[period][0].source.document_name}/{groups[period][1]}."
                )
                continue
            groups[period] = (doc, sheet, rows)

    leaf_rows_all = [r for _, _, rows in groups.values() for r in rows if r.is_leaf and r.display_value]
    reviewed = _llm_review_categories(leaf_rows_all, runtime, log_notes)

    for period, (doc, sheet, rows) in sorted(groups.items()):
        source: SourceDocument = doc.source
        leaves = [r for r in rows if r.is_leaf]
        convention = detect_sign_convention((r.code, r.display_value) for r in leaves if r.display_value is not None)
        if is_pre_closing(r.code for r in leaves if r.display_value):
            pre_closing.append(period)
        covered_periods.add(period)
        for r in leaves:
            if r.display_value is None:
                unreadable.append(
                    UnreadableItem(
                        id=f"unr_{source.document_id}_{sheet}_{r.row}",
                        description=f"Cuenta {r.code} {r.name} ({sheet}, celda {r.cell_ref}) con valor ilegible '{r.raw_value_text}'.",
                        reason="El saldo no es un número legible (error de Excel o texto). No se imputa ningún valor.",
                        citation=build_citation(source, sheet, r.quote, 0.3, r.cell_ref),
                    )
                )
                continue
            if r.display_value == 0:
                continue
            rule = rule_based_mapping(r.code, r.name)
            category, rationale, confidence = rule.category, rule.rationale, rule.confidence
            llm_view = reviewed.get(f"{r.sheet}:{r.row}:{r.period}")
            if llm_view is not None:
                if llm_view[0] != rule.category:
                    rationale = f"{rule.rationale} Ajustado por el agente: {llm_view[1]}"
                else:
                    rationale = f"{rule.rationale} Confirmado por el agente: {llm_view[1]}"
                category, confidence = llm_view[0], llm_view[2]
            value = to_engine_value(r.code, category, r.display_value, convention)
            accounts.append(
                MappedAccountItem(
                    raw_account_code=r.code,
                    raw_account_name=r.name or f"Cuenta {r.code}",
                    standard_category=category,  # type: ignore[arg-type]
                    period=period,
                    raw_value_cop=value * units_multiplier(source),
                    mapping_rationale=f"{rationale}{sign_note(convention, category)} (confianza de clasificación {confidence:.2f})",
                    citation=build_citation(source, sheet, r.quote, 0.99, r.cell_ref),
                )
            )
            if category == "UNMAPPED":
                unreadable.append(
                    UnreadableItem(
                        id=f"unm_{source.document_id}_{sheet}_{r.row}",
                        description=f"Cuenta {r.code} {r.name} ({sheet}) no mapeada a una categoría estándar.",
                        reason=rationale,
                        citation=build_citation(source, sheet, r.quote, 0.99, r.cell_ref),
                    )
                )
    return accounts, unreadable, pre_closing, covered_periods


def _statement_lines(documents: Sequence[SourceDocument]) -> dict[str, tuple[SourceDocument, str, str]]:
    """line_id -> (documento, página, texto de la línea) para páginas de estados financieros con cifras."""
    lines: dict[str, tuple[SourceDocument, str, str]] = {}
    for doc in documents:
        if doc.document_type != "FINANCIAL_STATEMENTS_PDF":
            continue
        for page in doc.pages:
            if not STATEMENT_PAGE_RE.search(page.content):
                continue
            for line_no, text in enumerate(page.content.splitlines(), start=1):
                if find_numbers(text):
                    lines[f"{doc.document_id}::{page.page_or_sheet}::{line_no}"] = (doc, page.page_or_sheet, text)
    return lines


def _signed_statement_value(category: str, nature: Optional[str], reported: float) -> float:
    magnitude = abs(reported)
    if category in ("REVENUE", "COGS", "SGA", "DA", "TAXES"):
        return -magnitude if nature == "CONTRA" else magnitude
    if category == "NET_INTEREST":
        return -magnitude if nature == "INCOME" else magnitude
    if category == "OTHER_OP_INCOME_EXP":
        return -magnitude if nature == "EXPENSE" else magnitude
    if category == "EQUITY":
        return reported
    return -magnitude if nature == "CONTRA" else magnitude


def map_pdf_statements(
    documents: Sequence[SourceDocument], covered_periods: set[str], runtime: AgentRuntime, log_notes: list[str]
) -> tuple[list[MappedAccountItem], list[UnreadableItem]]:
    lines = _statement_lines(documents)
    if not lines:
        return [], []
    if not runtime.uses_llm:
        docs = sorted({doc.document_name for doc, _, _ in lines.values()})
        return [], [
            UnreadableItem(
                id="unr_pdf_statements_rules_mode",
                description=f"Estados financieros en PDF ({', '.join(docs)}) no se mapearon a cuentas.",
                reason=(
                    "Sin LLM disponible, solo los balances de prueba en Excel/CSV se mapean automáticamente. "
                    "Cargue el balance de prueba o active un modelo (cloud u Ollama)."
                ),
            )
        ]
    listing = "\n".join(f"- line_id={lid} | {text}" for lid, (_, _, text) in lines.items())
    try:
        response = runtime.llm.complete_json(  # type: ignore[union-attr]
            INGESTOR_STATEMENTS,
            f"Periodos ya cubiertos por balances de prueba (no los mapees): {sorted(covered_periods) or 'ninguno'}\n"
            f"Líneas:\n{listing[:60_000]}",
            StatementMappingResponse,
            deal_id=runtime.deal_id,
            task="ingestor.statements",
        )
    except LLMError as exc:
        log_notes.append(f"No se pudieron clasificar líneas de EEFF en PDF: {exc}")
        return [], []

    accounts: list[MappedAccountItem] = []
    unreadable: list[UnreadableItem] = []
    seen: set[tuple[str, str]] = set()
    for item in response.items:
        if item.action != "MAP" or item.line_id not in lines or item.standard_category is None:
            continue
        if not item.period or not YEAR_RE.fullmatch(item.period) or item.period in covered_periods:
            continue
        if (item.line_id, item.period) in seen:
            continue
        seen.add((item.line_id, item.period))
        doc, page, text = lines[item.line_id]
        numbers = [value for raw, value in find_numbers(text) if not YEAR_RE.fullmatch(raw.strip("()"))]
        citation = build_citation(doc, page, text, 0.9)
        if item.column_index is None or item.column_index >= len(numbers):
            unreadable.append(
                UnreadableItem(
                    id=f"unr_{citation.citation_id}_{item.period}",
                    description=f"Línea '{text[:120]}' ({doc.document_name}, {page}) para {item.period}.",
                    reason="El agente señaló una columna que no existe en la línea; no se imputa valor.",
                    citation=citation,
                )
            )
            continue
        reported = numbers[item.column_index]
        value = _signed_statement_value(item.standard_category, item.nature, reported) * units_multiplier(doc)
        accounts.append(
            MappedAccountItem(
                raw_account_code=None,
                raw_account_name=text.split("|")[0].strip()[:160],
                standard_category=item.standard_category,
                period=item.period,
                raw_value_cop=value,
                mapping_rationale=(
                    f"Línea de EEFF en PDF clasificada por el agente: {item.rationale}. Cifra leída de la columna "
                    f"{item.column_index} de la línea y convertida desde {doc.reported_units}."
                ),
                citation=citation,
            )
        )
    return accounts, unreadable


def run_ingestor(parsed: Sequence[ParsedDocument], runtime: AgentRuntime) -> dict:
    timer = NodeTimer("node_ingestor_and_puc_mapper", runtime.effective_mode)
    calls_before = getattr(runtime.llm, "calls", 0)
    notes: list[str] = []
    documents = [p.source for p in parsed]
    accounts, unreadable, pre_closing, covered = map_trial_balances(parsed, runtime, notes)
    pdf_accounts, pdf_unreadable = map_pdf_statements(documents, covered, runtime, notes)
    accounts += pdf_accounts
    unreadable += pdf_unreadable
    for p in parsed:
        for page in p.scanned_pages:
            unreadable.append(
                UnreadableItem(
                    id=f"unr_scan_{p.source.document_id}_{page.replace(' ', '_')}",
                    description=f"{p.source.document_name} — {page} sin capa de texto.",
                    reason="Página escaneada: requiere OCR o una versión digital del documento.",
                )
            )
        notes.extend(p.warnings)
    mapped = [a for a in accounts if a.standard_category != "UNMAPPED"]
    if not mapped:
        raise IngestionError(
            "No se encontraron cifras financieras legibles. Cargue el balance de prueba (XLSX/CSV) o active un LLM "
            "para leer los estados financieros en PDF."
        )
    periods = sorted({a.period for a in accounts})
    return {
        "documents": documents,
        "mapped_accounts": accounts,
        "unreadable_items": unreadable,
        "pre_closing_periods": sorted(set(pre_closing) & set(periods)),
        "periods": periods,
        "processing_log": [
            timer.entry(
                f"{len(mapped)} cuentas mapeadas en {len(periods)} periodo(s); {len(unreadable)} ítem(s) ilegibles o no mapeados.",
                llm_calls=getattr(runtime.llm, "calls", 0) - calls_before,
                notes=notes,
            )
        ],
    }
