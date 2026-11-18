"""Construcción de contexto para los agentes y utilidades compartidas entre nodos."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

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


# Páginas de "Otros archivos" (fuentes complementarias): se envían al modelo solo si hablan de temas útiles
# para el screening; las demás se descartan para no meter ruido en el análisis.
RELEVANCE_KEYWORDS = re.compile(
    r"venta|ingreso|ebitda|utilidad|margen|deuda|activo|pasivo|patrimonio|flujo|caja|efectivo|cliente|proveedor|"
    r"contrato|socio|accionist|riesgo|valor|aval[úu]|arrend|canon|emplead|trabajador|producci|mercado|competen|"
    r"crecimiento|proyecci|presupuesto|cartera|inventario|impuesto|dian|litig|demanda|garant|cr[ée]dito|banco|"
    r"pr[ée]stamo|dividend|junta|asamblea|acta|gerente|representante|nit|tesis|inversi|adquisici|transacci|"
    r"exportaci|planta|capacidad|concentraci|contingen|provisi|seguro|licencia|ambiental|propiedad",
    re.IGNORECASE,
)
CHARS_PER_TOKEN = 3.0  # conservador para español con cifras y tablas
DEFAULT_INPUT_TOKENS = 16000  # clientes sin límite declarado (ej. simulados en tests)
SUPPLEMENTARY_SHARE = 0.35  # espacio máximo de las fuentes complementarias cuando las principales no caben


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


def is_supplementary(document: SourceDocument) -> bool:
    """Documento cargado en «Otros archivos»: contexto complementario, nunca fuente de cifras del motor."""
    return document.upload_slot == "OTHER"


def input_budget_chars(llm: Any, fixed_text: str = "") -> int:
    """Caracteres disponibles para documentos en una llamada, descontando prompt de sistema, esquema y partes fijas."""
    tokens = int(getattr(llm, "max_input_tokens", None) or DEFAULT_INPUT_TOKENS)
    return max(1500, int(tokens * CHARS_PER_TOKEN) - len(fixed_text) - 300)


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


@dataclass
class ContextBlock:
    """Una página (o fragmento de página) de un documento, lista para enviar al modelo."""

    text: str
    priority: tuple[int, int, int]
    supplementary: bool
    relevance: int


@dataclass
class ContextPlan:
    chunks: list[str]
    primary_pages: int = 0
    supplementary_pages: int = 0
    irrelevant_supplementary: int = 0
    dropped_primary: int = 0
    dropped_supplementary: int = 0

    def note(self) -> Optional[str]:
        if not self.chunks:
            return None
        parts = [f"Contexto enviado al modelo en {len(self.chunks)} parte(s): {self.primary_pages} página(s) de documentos principales"]
        if self.supplementary_pages or self.irrelevant_supplementary or self.dropped_supplementary:
            parts.append(f"{self.supplementary_pages} de «Otros archivos»")
        text = " y ".join(parts) + "."
        if self.irrelevant_supplementary:
            text += f" {self.irrelevant_supplementary} página(s) de «Otros archivos» se descartaron por no tener información relevante."
        if self.dropped_primary or self.dropped_supplementary:
            text += (
                f" Por el límite del modelo no se enviaron {self.dropped_primary} página(s) principales y "
                f"{self.dropped_supplementary} complementarias de menor prioridad."
            )
        return text


def _split_lines(text: str, max_chars: int) -> list[str]:
    """Divide un texto por renglones en fragmentos de hasta ``max_chars`` (un renglón enorme se corta)."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        while len(line) > max_chars:
            if current:
                parts.append("\n".join(current))
                current, size = [], 0
            parts.append(line[:max_chars])
            line = line[max_chars:]
        if size + len(line) + 1 > max_chars and current:
            parts.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts


def context_blocks(
    documents: Sequence[SourceDocument], include_types: Optional[set[str]] = None, max_block_chars: Optional[int] = None
) -> list[ContextBlock]:
    """Páginas de los documentos cualitativos con su prioridad.

    Fuentes principales (certificado, notas relevantes de los EEFF, avalúos y teaser cargados como principales)
    primero; las de «Otros archivos» se etiquetan como complementarias y se ordenan por relevancia. El balance de
    prueba no se envía: sus cifras ya están en el motor.
    """
    blocks: list[ContextBlock] = []
    for doc_idx, doc in enumerate(documents):
        if include_types is not None and doc.document_type not in include_types:
            continue
        supplementary = is_supplementary(doc)
        if doc.document_type == "TRIAL_BALANCE_XLSX" and not supplementary:
            continue
        priority = DOC_TYPE_PRIORITY.get(doc.document_type, 5)
        role = "FUENTE COMPLEMENTARIA («Otros archivos»)" if supplementary else "FUENTE PRINCIPAL"
        for idx, page in enumerate(doc.pages):
            content = page.content.strip()
            if not content:
                continue
            hits = len({m.group(0).lower() for m in RELEVANCE_KEYWORDS.finditer(content)})
            if supplementary:
                relevance = hits + (2 if NOTE_KEYWORDS.search(content) else 0)
            else:
                relevance = 0 if doc.document_type != "FINANCIAL_STATEMENTS_PDF" or NOTE_KEYWORDS.search(content) else 1
            header = (
                f"### [{role}] document_id={doc.document_id} | {doc.document_name} | "
                f"page_or_sheet={page.page_or_sheet} | unidades={doc.reported_units}"
            )
            pieces = [content] if max_block_chars is None else _split_lines(content, max(400, max_block_chars - len(header) - 30))
            for n, piece in enumerate(pieces, start=1):
                suffix = f" | fragmento {n}/{len(pieces)}" if len(pieces) > 1 else ""
                blocks.append(
                    ContextBlock(
                        text=f"{header}{suffix}\n{piece}",
                        priority=(priority * 10 + (relevance if not supplementary else 0), doc_idx, idx * 100 + n),
                        supplementary=supplementary,
                        relevance=relevance,
                    )
                )
    blocks.sort(key=lambda b: b.priority)
    return blocks


def plan_context(
    documents: Sequence[SourceDocument],
    chunk_chars: int,
    max_chunks: int = 1,
    include_types: Optional[set[str]] = None,
    supplementary_share: float = SUPPLEMENTARY_SHARE,
) -> ContextPlan:
    """Reparte las páginas en hasta ``max_chunks`` partes de ``chunk_chars`` caracteres.

    * Las fuentes complementarias sin relevancia se descartan.
    * Si todo no cabe, las complementarias se limitan a ``supplementary_share`` del espacio total, para que
      nunca desplacen a los documentos obligatorios; si las principales son pocas, aprovechan el espacio libre.
    """
    chunk_chars = max(800, chunk_chars)
    blocks = context_blocks(documents, include_types, max_block_chars=chunk_chars)
    primary = [b for b in blocks if not b.supplementary]
    supplementary = sorted(
        (b for b in blocks if b.supplementary and b.relevance > 0), key=lambda b: (-b.relevance, b.priority)
    )
    plan = ContextPlan(chunks=[], irrelevant_supplementary=sum(1 for b in blocks if b.supplementary and b.relevance == 0))
    total = chunk_chars * max_chunks
    reserve = min(sum(len(b.text) + 2 for b in supplementary), int(total * supplementary_share))

    bins: list[list[str]] = [[] for _ in range(max_chunks)]
    sizes = [0] * max_chunks

    def place(block: ContextBlock, limit_total: int) -> bool:
        size = len(block.text) + 2
        if sum(sizes) + size > limit_total:
            return False
        for i in range(max_chunks):
            if sizes[i] + size <= chunk_chars:
                bins[i].append(block.text)
                sizes[i] += size
                return True
        return False

    for block in primary:
        if place(block, total - reserve):
            plan.primary_pages += 1
        else:
            plan.dropped_primary += 1
    for block in supplementary:
        if place(block, total):
            plan.supplementary_pages += 1
        else:
            plan.dropped_supplementary += 1
    plan.chunks = ["\n\n".join(b) for b in bins if b]
    return plan


def documents_context(
    documents: Sequence[SourceDocument],
    max_chars: int = 60_000,
    include_types: Optional[set[str]] = None,
) -> str:
    """Texto de los documentos cualitativos en un solo bloque de hasta ``max_chars`` (prioridad: certificado,
    notas relevantes, avalúos, teaser; las fuentes complementarias, solo si son relevantes)."""
    plan = plan_context(documents, max_chars, 1, include_types)
    return plan.chunks[0] if plan.chunks else ""


def split_to_size(text: str, max_chars: int) -> list[str]:
    """Divide una parte de contexto respetando los encabezados ``### `` de cada página cuando es posible."""
    if len(text) <= max_chars:
        return [text]
    sections = re.split(r"\n\n(?=### )", text)
    out: list[str] = []
    current = ""
    for section in sections:
        pieces = [section] if len(section) <= max_chars else _split_lines(section, max_chars)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                out.append(current)
                current = ""
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        out.append(current)
    return out


def run_chunked(
    runtime: "AgentRuntime",
    *,
    system: str,
    schema: type,
    task: str,
    chunks: Sequence[str],
    make_user: Callable[[str, int, int], str],
    fixed_text: str,
    notes: list[str],
    max_calls: int = 8,
) -> list[Any]:
    """Llama al modelo una vez por parte de contexto y devuelve las respuestas válidas.

    Si el proveedor rechaza una parte por tamaño (límite de tokens del plan gratuito), el cliente reduce su
    presupuesto y las partes pendientes se vuelven a dividir. Si falla por otra causa (cuota, red), se conservan
    las respuestas ya obtenidas; si no hay ninguna, se propaga el error para degradar a reglas.
    """
    from app.services.llm_client import LLMContextTooLarge, LLMError
    from app.services.llm_client import schema_instructions

    overhead = system + schema_instructions(schema) + fixed_text
    queue = list(chunks)
    results: list[Any] = []
    error: Optional[Exception] = None
    calls = 0
    done = 0
    while queue and calls < max_calls:
        chunk = queue.pop(0)
        calls += 1
        try:
            results.append(
                runtime.llm.complete_json(  # type: ignore[union-attr]
                    system, make_user(chunk, done + 1, done + 1 + len(queue)), schema, deal_id=runtime.deal_id, task=task
                )
            )
            done += 1
        except LLMContextTooLarge as exc:
            budget = input_budget_chars(runtime.llm, overhead)
            pieces = split_to_size(chunk, budget) if budget < len(chunk) else split_to_size(chunk, max(800, len(chunk) // 2))
            if len(pieces) < 2:
                error = exc
                break
            queue = pieces + [p for rest in queue for p in split_to_size(rest, budget)]
        except LLMError as exc:
            error = exc
            break
    skipped = len(queue)
    if not results:
        if error is not None:
            raise error
        return results
    if error is not None or skipped:
        notes.append(
            f"{task}: se analizaron {done} parte(s) del contexto; {skipped + (1 if error else 0)} quedaron sin analizar"
            + (f" ({str(error)[:160]})." if error else " (límite de llamadas por agente).")
        )
    return results


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
