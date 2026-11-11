"""Nodo 5 — Agente Redactor de Comité (Memo de Screening de 2 páginas).

El memo es una PLANTILLA: las cifras calculadas son marcadores {{...}} que el renderizador determinista
resuelve con la salida del motor, y las fuentes son [[cite:id]] verificados contra el expediente.
Sin LLM se genera una plantilla determinista con la misma estructura.
"""

from __future__ import annotations

from typing import Sequence

from app.agents.context import AgentRuntime, NodeTimer, citation_catalog, engine_summary, placeholder_catalog
from app.agents.llm_schemas import MemoResponse
from app.agents.prompts import IC_MEMO_WRITER
from app.schemas.deal import (
    CorporateProfile,
    EbitdaAdjustment,
    MappedAccountItem,
    MissingInfoItem,
    RedFlagItem,
    SourceCitation,
)
from app.schemas.financials import FinancialEngineResult
from app.services.llm_client import LLMError
from app.services.memo_renderer import CITATION_RE, extract_placeholders, render_memo

SEVERITY_LABEL = {"CRITICAL_DEALBREAKER": "Crítico", "HIGH": "Alto", "MEDIUM": "Medio"}


def _cite(citation: SourceCitation | None) -> str:
    return f" [[cite:{citation.citation_id}]]" if citation is not None else ""


def deterministic_memo(
    company: dict,
    profile: CorporateProfile,
    result: FinancialEngineResult,
    accounts: Sequence[MappedAccountItem],
    adjustments: Sequence[EbitdaAdjustment],
    red_flags: Sequence[RedFlagItem],
    missing: Sequence[MissingInfoItem],
) -> str:
    last = result.periods[-1]
    first = result.periods[0]
    prev = result.periods[-2] if len(result.periods) > 1 else None
    revenue_cites = "".join(
        _cite(a.citation) for a in [a for a in accounts if a.period == last and a.standard_category == "REVENUE"][:3]
    )
    lines = [
        f"# Memo de Screening — {company['company_name']}",
        "",
        f"**Para:** Comité de Inversión · **Etapa:** Screening preliminar · **Periodo analizado:** {first}–{last}",
        "**Nota metodológica:** memo generado por reglas deterministas (sin LLM). Las cifras provienen del motor financiero; "
        "la tesis y la recomendación deben completarlas el analista.",
        "",
        "## 1. Resumen ejecutivo",
        "",
        f"{company['company_name']} (NIT {company['nit']}{_cite(profile.nit.citation)}; CIIU {company['ciiu_code']}{_cite(profile.ciiu_primary.citation)}). "
        f"En {last} registró ingresos netos de {{{{metric:revenue:{last}}}}}{revenue_cites}"
        + (f", con un crecimiento de {{{{metric:revenue_growth_yoy_pct:{last}}}}} frente a {prev}" if prev else "")
        + f". El EBITDA reportado fue {{{{metric:ebitda_reported:{last}}}}} (margen {{{{metric:ebitda_reported_margin_pct:{last}}}}}) "
        f"y el EBITDA ajustado {{{{metric:ebitda_adjusted:{last}}}}} (margen {{{{metric:ebitda_adjusted_margin_pct:{last}}}}}).",
        "",
        "**Recomendación preliminar:** pendiente del criterio del analista.",
        "",
        "## 2. Tesis de inversión",
        "",
    ]
    if len(result.periods) > 1:
        lines.append(f"- Crecimiento compuesto de ingresos {first}–{last}: {{{{growth:revenue_cagr_pct}}}}.")
    if result.valuation.sector_operating_benchmarks:
        lines.append(
            f"- Margen bruto {last}: {{{{metric:gross_margin_pct:{last}}}}} vs. mediana sectorial {{{{benchmark:gross_margin_pct:median}}}}."
        )
        lines.append(
            f"- Margen EBITDA ajustado {last}: {{{{metric:ebitda_adjusted_margin_pct:{last}}}}} vs. mediana sectorial "
            "{{benchmark:ebitda_margin_pct:median}}."
        )
    lines += [
        "",
        "## 3. Calidad del EBITDA",
        "",
        f"| Concepto | {last} |",
        "|---|---|",
        f"| EBITDA reportado | {{{{metric:ebitda_reported:{last}}}}} |",
        f"| Ajustes aceptados | {{{{bridge:{last}:total_accepted}}}} |",
        f"| Ajustes pendientes (excluidos) | {{{{bridge:{last}:total_pending}}}} |",
        f"| **EBITDA ajustado** | **{{{{metric:ebitda_adjusted:{last}}}}}** |",
        "",
    ]
    last_adjustments = [a for a in adjustments if a.period == last]
    if last_adjustments:
        lines += [f"- {a.title} ({a.status}){_cite(a.citation)}" for a in last_adjustments]
    else:
        lines.append("- No se identificaron ajustes automáticamente; el analista puede agregarlos en el sandbox de EBITDA.")
    lines += ["", "## 4. Valoración preliminar", ""]
    if result.valuation.status == "OK":
        lines += [
            "| Escenario | Múltiplo | Enterprise Value | Deuda neta | Equity Value |",
            "|---|---|---|---|---|",
        ]
        for s in result.valuation.scenarios:
            label = {"CONSERVADOR": "Conservador (P25)", "BASE": "Base (Mediana)", "OPTIMISTA": "Optimista (P75)"}[s.scenario]
            lines.append(
                f"| {label} | {{{{valuation:{s.scenario}:multiple}}}} | {{{{valuation:{s.scenario}:enterprise_value}}}} | "
                f"{{{{valuation:{s.scenario}:net_debt}}}} | {{{{valuation:{s.scenario}:equity_value}}}} |"
            )
        lines.append(
            f"\nDeuda neta / EBITDA ajustado {last}: {{{{metric:net_debt_to_ebitda_adjusted:{last}}}}}. Múltiplos sectoriales referenciales ({{{{valuation:sector_label}}}})."
        )
    else:
        lines.append(f"Valoración no disponible: {result.valuation.message}")
    lines += ["", "## 5. Riesgos críticos", ""]
    if red_flags:
        for n, flag in enumerate(red_flags[:6], start=1):
            lines.append(f"{n}. **{flag.title}** ({SEVERITY_LABEL[flag.severity]}){_cite(flag.citations[0])}")
    else:
        lines.append("Sin red flags automáticas; revisar con el agente escéptico en modo LLM.")
    lines += ["", "## 6. Próximos pasos", ""]
    lines += [f"- Solicitar: {m.requested_document_or_clarification}" for m in missing if m.priority == "MUST_HAVE_FOR_IC"][:6]
    lines.append("- Validar los ajustes de EBITDA en el sandbox y completar la tesis de inversión.")
    return "\n".join(lines) + "\n"


def sanitize_memo(markdown: str, valid_ids: set[str]) -> tuple[str, int]:
    """Elimina citas cuyo id no existe en el expediente (un LLM puede inventarlas)."""
    removed = 0

    def _sub(match):
        nonlocal removed
        if match.group(1) in valid_ids:
            return match.group(0)
        removed += 1
        return "⟦cita no verificada⟧"

    return CITATION_RE.sub(_sub, markdown), removed


def run_memo_writer(state: dict, runtime: AgentRuntime, all_citations: Sequence[SourceCitation]) -> dict:
    timer = NodeTimer("node_ic_memo_writer", runtime.effective_mode)
    calls_before = getattr(runtime.llm, "calls", 0)
    notes: list[str] = []
    result: FinancialEngineResult = state["financials"]
    valid_ids = {c.citation_id for c in all_citations}
    memo = None
    if runtime.uses_llm:
        flags = "\n".join(f"- [{f.severity}] {f.title} (citas: {', '.join(c.citation_id for c in f.citations)})" for f in state["red_flags"])
        adjs = "\n".join(f"- {a.id} [{a.status}] {a.period} {a.title} (cita {a.citation.citation_id})" for a in state["ebitda_adjustments"])
        missing = "\n".join(f"- {m.priority}: {m.requested_document_or_clarification}" for m in state["missing_info"])
        company = state["company"]
        user = (
            f"EMPRESA: {company['company_name']} | NIT {company['nit']} | CIIU {company['ciiu_code']} | {company['city']}\n\n"
            f"{engine_summary(result)}\n\n{placeholder_catalog(result)}\n\nAJUSTES:\n{adjs or '(ninguno)'}\n\n"
            f"RED FLAGS:\n{flags or '(ninguna)'}\n\nINFORMACIÓN FALTANTE:\n{missing or '(ninguna)'}\n\n{citation_catalog(all_citations)}"
        )
        try:
            response = runtime.llm.complete_json(  # type: ignore[union-attr]
                IC_MEMO_WRITER, user, MemoResponse, deal_id=runtime.deal_id, task="memo_writer"
            )
            memo, removed = sanitize_memo(response.memo_markdown, valid_ids)
            if removed:
                notes.append(f"{removed} cita(s) inventadas por el LLM fueron removidas del memo.")
            unresolved = render_memo(memo, result).count("MISSING_DATA")
            if unresolved:
                notes.append(f"{unresolved} marcador(es) del memo no se pudieron resolver y quedan como MISSING_DATA.")
        except LLMError as exc:
            notes.append(f"Fallo del LLM redactor ({exc}); se usa plantilla determinista.")
            memo = None
    if memo is None:
        memo = deterministic_memo(
            state["company"],
            state["corporate_profile"],
            result,
            state["mapped_accounts"],
            state["ebitda_adjustments"],
            state["red_flags"],
            state["missing_info"],
        )
    return {
        "memo_template": memo,
        "processing_log": [
            timer.entry(
                f"Memo generado ({len(extract_placeholders(memo))} marcadores, {len(CITATION_RE.findall(memo))} citas).",
                llm_calls=getattr(runtime.llm, "calls", 0) - calls_before,
                notes=notes,
            )
        ],
    }
