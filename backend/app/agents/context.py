"""Construcción de contexto para los agentes y utilidades compartidas entre nodos."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from app.schemas.deal import SourceCitation, SourceDocument
from app.schemas.financials import FinancialEngineResult
from app.services.document_parser import UNIT_MULTIPLIERS
from app.services.llm_client import StructuredLLM
from app.services.memo_renderer import format_cop_millions, format_days, format_multiple, format_pct

DOC_TYPE_PRIORITY = {
    "CHAMBER_OF_COMMERCE_CERT": 0,
    "FINANCIAL_STATEMENTS_PDF": 1,
    "APPRAISAL": 2,
    "TEASER": 3,
    "OTHER": 4,
    "TRIAL_BALANCE_XLSX": 9,
}
NOTE_KEYWORDS = re.compile(
    r"parte[s]? relacionad|accionist|socio|familiar|arrend|canon|honorari|litig|proceso|demanda|contingen|provisi[óo]n|"
    r"dian|requerimiento|impuesto|covenant|cr[ée]dito|obligaciones financieras|garant|hipoteca|cartera|deterioro|"
    r"cliente|reorganizaci|club|veh[íi]culo|no recurrente|extraordinari|dictamen|[ée]nfasis|salvedad|empresa en marcha",
    re.IGNORECASE,
)


@dataclass
class AgentRuntime:
    """Dependencias de una ejecución del grafo (una por deal: aislamiento estricto)."""

    deal_id: str
    effective_mode: str
    benchmarks: Mapping[str, Any]
    llm: Optional[StructuredLLM] = None

    @property
    def uses_llm(self) -> bool:
        return self.llm is not None and self.effective_mode in ("CLOUD_API", "LOCAL_OLLAMA")


@dataclass
class NodeTimer:
    node: str
    mode: str
    started: float = field(default_factory=time.perf_counter)

    def entry(self, message: str, llm_calls: int = 0, **extra: Any) -> dict:
        return {
            "node": self.node,
            "mode": self.mode,
            "duration_ms": round((time.perf_counter() - self.started) * 1000, 2),
            "llm_calls": llm_calls,
            "message": message,
            **extra,
        }


def units_multiplier(document: SourceDocument) -> float:
    return UNIT_MULTIPLIERS.get(document.reported_units, 1.0)


def documents_context(
    documents: Sequence[SourceDocument],
    max_chars: int = 60_000,
    include_types: Optional[set[str]] = None,
) -> str:
    """Texto de los documentos cualitativos, priorizando certificado, notas relevantes, avalúos y teaser."""
    blocks: list[tuple[int, int, str]] = []
    for doc in documents:
        if include_types is not None and doc.document_type not in include_types:
            continue
        if doc.document_type == "TRIAL_BALANCE_XLSX":
            continue
        priority = DOC_TYPE_PRIORITY.get(doc.document_type, 5)
        for idx, page in enumerate(doc.pages):
            if not page.content.strip():
                continue
            relevance = 0 if doc.document_type != "FINANCIAL_STATEMENTS_PDF" or NOTE_KEYWORDS.search(page.content) else 1
            header = f"### document_id={doc.document_id} | {doc.document_name} | page_or_sheet={page.page_or_sheet} | unidades={doc.reported_units}"
            blocks.append((priority * 10 + relevance, idx, f"{header}\n{page.content}"))
    blocks.sort(key=lambda b: (b[0], b[1]))
    out: list[str] = []
    used = 0
    for _, _, text in blocks:
        if used + len(text) > max_chars:
            remaining = max_chars - used
            if remaining > 500:
                out.append(text[:remaining] + "\n[...truncado...]")
            break
        out.append(text)
        used += len(text)
    return "\n\n".join(out)


def engine_summary(result: FinancialEngineResult) -> str:
    """Métricas del motor ya formateadas para que los agentes las citen sin recalcular."""
    lines = ["MÉTRICAS DEL MOTOR DETERMINISTA (no recalcular):"]
    for inc, bal, wc, lev in zip(result.income_statement, result.balance_sheet, result.working_capital, result.leverage):
        p = inc.period
        lines.append(
            f"- {p}: ingresos {format_cop_millions(inc.revenue.value_cop)} (YoY {format_pct(inc.revenue_growth_yoy_pct) or 'n/a'}); "
            f"margen bruto {format_pct(inc.gross_margin_pct) or 'n/a'}; EBITDA reportado {format_cop_millions(inc.ebitda_reported_cop)} "
            f"({format_pct(inc.ebitda_reported_margin_pct) or 'n/a'}); EBITDA ajustado {format_cop_millions(inc.ebitda_adjusted_cop)} "
            f"({format_pct(inc.ebitda_adjusted_margin_pct) or 'n/a'}); utilidad neta {format_cop_millions(inc.net_income_cop)}; "
            f"caja {format_cop_millions(bal.cash.value_cop)}; DSO {format_days(wc.dso_days) or 'n/a'}; DIO {format_days(wc.dio_days) or 'n/a'}; "
            f"DPO {format_days(wc.dpo_days) or 'n/a'}; deuda financiera neta {format_cop_millions(lev.net_financial_debt_cop)}; "
            f"Deuda neta/EBITDA ajustado {format_multiple(lev.net_debt_to_ebitda_adjusted) or 'n/s'}; "
            f"Deuda neta/EBITDA reportado {format_multiple(lev.net_debt_to_ebitda_reported) or 'n/s'}; "
            f"balance {'cuadra' if bal.balance_check.is_balanced else 'DESCUADRADO por ' + str(format_cop_millions(bal.balance_check.difference_cop))}."
        )
    g = result.growth
    lines.append(f"- TCAC ingresos {g.first_period}-{g.last_period}: {format_pct(g.revenue_cagr_pct) or 'n/a'}")
    v = result.valuation
    lines.append(f"- Valoración ({v.status}, sector {v.sector_label or 'sin benchmark'}):")
    for s in v.scenarios:
        lines.append(
            f"  - {s.scenario}: múltiplo {format_multiple(s.ev_ebitda_multiple)}, EV {format_cop_millions(s.enterprise_value_cop)}, "
            f"Equity {format_cop_millions(s.equity_value_cop)}"
        )
    for metric, stats in v.sector_operating_benchmarks.items():
        lines.append(f"  - benchmark {metric}: P25 {stats.get('p25')}, mediana {stats.get('median')}, P75 {stats.get('p75')}")
    c = result.contingencies
    lines.append(
        f"- Contingencias no provisionadas (probables/posibles): {format_cop_millions(c.unprovisioned_probable_or_possible_cop)} "
        f"= {format_pct(c.unprovisioned_pct_of_adjusted_ebitda) or 'n/a'} del EBITDA ajustado."
    )
    for w in result.warnings:
        lines.append(f"- ADVERTENCIA {w.code}: {w.message}")
    return "\n".join(lines)


def placeholder_catalog(result: FinancialEngineResult) -> str:
    periods = ", ".join(result.periods)
    scenarios = ", ".join(s.scenario for s in result.valuation.scenarios) or "(sin escenarios)"
    benchmark_metrics = ", ".join(result.valuation.sector_operating_benchmarks) or "(sin benchmark)"
    return (
        "MARCADORES DISPONIBLES (periodos: " + periods + "):\n"
        "- {{metric:<revenue|revenue_growth_yoy_pct|gross_profit|gross_margin_pct|ebitda_reported|ebitda_reported_margin_pct|"
        "ebitda_adjusted|ebitda_adjusted_margin_pct|net_income|net_margin_pct|cash|total_assets|nwc|dso_days|dio_days|dpo_days|"
        "gross_debt|net_debt|net_debt_to_ebitda_reported|net_debt_to_ebitda_adjusted>:<periodo>}}\n"
        "- {{growth:revenue_cagr_pct}}, {{growth:ebitda_adjusted_cagr_pct}}\n"
        f"- {{{{valuation:<{scenarios}>:<multiple|enterprise_value|net_debt|equity_value|implied_ev_revenue>}}}}, {{{{valuation:sector_label}}}}\n"
        "- {{bridge:<periodo>:<total_accepted|total_pending|total_rejected>}}\n"
        "- {{contingencies:<unprovisioned|total_claimed|pct_adj_ebitda|pct_base_equity>}}\n"
        f"- {{{{benchmark:<{benchmark_metrics}>:<p25|median|p75>}}}}"
    )


def citation_catalog(citations: Sequence[SourceCitation], max_items: int = 180, quote_chars: int = 160) -> str:
    """Catálogo id -> fuente y cita abreviada. Prioriza citas de notas/certificados sobre filas de Excel."""
    unique: dict[str, SourceCitation] = {}
    for c in citations:
        unique.setdefault(c.citation_id, c)
    ordered = sorted(unique.values(), key=lambda c: (c.page_or_sheet.startswith("BP_") or "xlsx" in c.document_name.lower(), c.citation_id))
    lines = []
    for c in ordered[:max_items]:
        quote = c.exact_quote if len(c.exact_quote) <= quote_chars else c.exact_quote[:quote_chars] + "…"
        lines.append(f"- {c.citation_id}: [{c.document_name} — {c.page_or_sheet}] \"{quote}\"")
    return "CATÁLOGO DE CITAS VÁLIDAS:\n" + "\n".join(lines)
