"""Chat contextual con el expediente.

* Preguntas de escenario ("¿qué pasa con el EBITDA si excluimos el arriendo pagado al socio?"): el chat
  identifica los ajustes involucrados, el motor determinista recalcula y la respuesta compara
  antes/después. El LLM (si existe) solo redacta e indica qué ajustes probar; nunca calcula.
* Preguntas de fuentes: devuelve las citas literales relevantes.
* Sin LLM funciona con un enrutador de intenciones determinista.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Optional, Sequence

from app.agents.context import citation_catalog, engine_summary, placeholder_catalog
from app.agents.llm_schemas import ChatLLMResponse
from app.agents.prompts import DOSSIER_CHAT
from app.schemas.api import ChatResponse, KeyMetrics, ScenarioResult
from app.schemas.deal import DealDossier, EbitdaAdjustment, SourceCitation
from app.schemas.financials import FinancialEngineResult
from app.services.financial_engine import recalculate_dossier
from app.services.llm_client import LLMError, StructuredLLM
from app.services.memo_renderer import CITATION_RE, format_cop_millions, format_multiple, format_pct, render_memo

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "RELATED_PARTY_RENT": ("arriendo", "arrendamiento", "canon", "bodega", "alquiler"),
    "OWNER_COMPENSATION": ("sueldo", "salario", "familiar", "remuneracion", "nomina", "compensacion", "conyuge", "hija"),
    "NON_RECURRING_LEGAL": ("legal", "abogad", "honorario", "litigio", "demanda", "defensa"),
    "PERSONAL_EXPENSES": ("personal", "club", "vehiculo", "carro"),
    "OTHER": ("venta de activo", "venta de vehiculo", "utilidad en venta", "no recurrente"),
}
EXCLUDE_RE = re.compile(r"\b(exclu\w*|quit\w*|sin|rechaz\w*|elimin\w*|sac\w*|no acept\w*|desactiv\w*)\b")
INCLUDE_RE = re.compile(r"\b(inclu\w*|acept\w*|sum\w*|agreg\w*|activ\w*|normaliz\w*)\b")
SOURCE_RE = re.compile(r"\b(fuente|de donde|cita|soporte|evidencia|documento|pagina|celda)\b")
STOPWORDS = {"cual", "cuál", "donde", "fuente", "sale", "esta", "este", "para", "como", "cuanto", "tiene", "dato", "cifra", "que", "del", "los", "las"}


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def key_metrics(result: FinancialEngineResult, period: str) -> KeyMetrics:
    inc = next(r for r in result.income_statement if r.period == period)
    lev = next(r for r in result.leverage if r.period == period)
    base = next((s for s in result.valuation.scenarios if s.scenario == "BASE"), None)
    is_valuation_period = result.valuation.valuation_period == period
    return KeyMetrics(
        period=period,
        ebitda_adjusted_cop=inc.ebitda_adjusted_cop,
        ebitda_adjusted_margin_pct=inc.ebitda_adjusted_margin_pct,
        net_debt_to_ebitda_adjusted=lev.net_debt_to_ebitda_adjusted,
        base_enterprise_value_cop=base.enterprise_value_cop if base and is_valuation_period else None,
        base_equity_value_cop=base.equity_value_cop if base and is_valuation_period else None,
    )


def scenario_table(before: KeyMetrics, after: KeyMetrics) -> str:
    rows = [
        ("EBITDA ajustado", format_cop_millions(before.ebitda_adjusted_cop), format_cop_millions(after.ebitda_adjusted_cop)),
        ("Margen EBITDA ajustado", format_pct(before.ebitda_adjusted_margin_pct), format_pct(after.ebitda_adjusted_margin_pct)),
        ("Deuda neta / EBITDA ajustado", format_multiple(before.net_debt_to_ebitda_adjusted), format_multiple(after.net_debt_to_ebitda_adjusted)),
    ]
    if before.base_enterprise_value_cop is not None:
        rows.append(("Enterprise Value (Base)", format_cop_millions(before.base_enterprise_value_cop), format_cop_millions(after.base_enterprise_value_cop)))
        rows.append(("Equity Value (Base)", format_cop_millions(before.base_equity_value_cop), format_cop_millions(after.base_equity_value_cop)))
    lines = [f"| Métrica ({before.period}) | Actual | Escenario |", "|---|---|---|"]
    lines += [f"| {name} | {a or 'n/s'} | {b or 'n/s'} |" for name, a, b in rows]
    return "\n".join(lines)


def _matching_adjustments(message: str, adjustments: Sequence[EbitdaAdjustment], period: str) -> list[EbitdaAdjustment]:
    text = _plain(message)
    direct = [a for a in adjustments if a.id.lower() in text]
    if direct:
        return direct
    categories = {cat for cat, words in TOPIC_KEYWORDS.items() if any(w in text for w in words)}
    return [a for a in adjustments if a.category in categories and a.period == period]


def _run_scenario(
    dossier: DealDossier,
    benchmarks: Mapping,
    base: FinancialEngineResult,
    overrides: dict[str, str],
    description: str,
) -> tuple[ScenarioResult, FinancialEngineResult]:
    _, scenario_result = recalculate_dossier(dossier, benchmarks, overrides)
    period = scenario_result.valuation.valuation_period
    affected_periods = {a.period for a in dossier.ebitda_adjustments if a.id in overrides}
    if len(affected_periods) == 1:
        period = next(iter(affected_periods))
    return (
        ScenarioResult(
            overrides=overrides,  # type: ignore[arg-type]
            description=description,
            before=key_metrics(base, period),
            after=key_metrics(scenario_result, period),
        ),
        scenario_result,
    )


def _resolve_citations(markdown: str, index: dict[str, SourceCitation]) -> list[SourceCitation]:
    seen: list[str] = []
    for cid in CITATION_RE.findall(markdown):
        if cid in index and cid not in seen:
            seen.append(cid)
    return [index[c] for c in seen]


def rules_answer(dossier: DealDossier, base: FinancialEngineResult, benchmarks: Mapping, message: str) -> ChatResponse:
    text = _plain(message)
    index = dossier.citation_index()
    years = re.findall(r"20\d{2}", text)
    period = years[0] if years and years[0] in dossier.periods else base.periods[-1]
    matches = _matching_adjustments(message, dossier.ebitda_adjustments, period)

    if matches and (EXCLUDE_RE.search(text) or INCLUDE_RE.search(text) or "que pasa" in text or "impacto" in text):
        mentions_adjustment = "ajuste" in text
        if EXCLUDE_RE.search(text) and mentions_adjustment:
            intent = "REJECTED"  # "excluir el ajuste" = no normalizar
        elif EXCLUDE_RE.search(text) or INCLUDE_RE.search(text):
            intent = "ACCEPTED"  # "excluir el arriendo/gasto" = normalizarlo (sumarlo de vuelta)
        else:
            intent = "REJECTED"
        overrides: dict[str, str] = {}
        notes: list[str] = []
        for adj in matches:
            target = intent
            if adj.status == intent:
                target = "REJECTED" if intent == "ACCEPTED" else "ACCEPTED"
                notes.append(f"«{adj.title}» ya estaba en estado {adj.status}; se muestra el impacto de revertirlo.")
            overrides[adj.id] = target
        description = "; ".join(f"{a.title} → {overrides[a.id]}" for a in matches)
        scenario, _ = _run_scenario(dossier, benchmarks, base, overrides, description)
        delta = scenario.after.ebitda_adjusted_cop - scenario.before.ebitda_adjusted_cop
        cites = " ".join(f"[[cite:{a.citation.citation_id}]]" for a in matches)
        answer = (
            f"**Escenario simulado con el motor determinista** ({len(matches)} ajuste(s) {cites}):\n\n"
            + "\n".join(f"- {a.title} ({a.period}): {format_cop_millions(a.amount_cop)} → {overrides[a.id]}" for a in matches)
            + ("\n\n" + "\n".join(f"_{n}_" for n in notes) if notes else "")
            + f"\n\n{scenario_table(scenario.before, scenario.after)}\n\n"
            f"Variación del EBITDA ajustado {scenario.before.period}: **{format_cop_millions(delta)}**. "
            "El escenario no modifica el expediente; para aplicarlo use los switches del puente de EBITDA."
        )
        return ChatResponse(answer_markdown=answer, citations=_resolve_citations(answer, index), scenario=scenario, mode="RULES")

    if SOURCE_RE.search(text) or matches:
        tokens = [t for t in re.findall(r"[a-z0-9]{4,}", text) if t not in STOPWORDS]
        scored = []
        for cit in index.values():
            haystack = _plain(f"{cit.exact_quote} {cit.document_name}")
            score = sum(1 for t in tokens if t in haystack)
            if score:
                scored.append((score, cit.citation_id))
        scored.sort(key=lambda s: (-s[0], s[1]))
        top = [index[cid] for _, cid in scored[:5]]
        if matches:
            top = [a.citation for a in matches] + [c for c in top if c.citation_id not in {a.citation.citation_id for a in matches}]
            top = top[:5]
        if top:
            answer = "Fuentes encontradas en el expediente:\n\n" + "\n".join(
                f"- **{c.document_name} — {c.page_or_sheet}** ({c.cell_or_line_ref or 's/r'}): “{c.exact_quote[:220]}” [[cite:{c.citation_id}]]"
                for c in top
            )
        else:
            answer = "No encontré una fuente en el expediente que responda esa pregunta. El dato debe tratarse como MISSING_DATA."
        return ChatResponse(answer_markdown=answer, citations=_resolve_citations(answer, index), mode="RULES")

    last = base.periods[-1]
    critical = [f for f in dossier.red_flags if f.status == "ACTIVE"][:3]
    template = (
        f"Resumen de {dossier.company_name} ({last}): ingresos {{{{metric:revenue:{last}}}}}, EBITDA ajustado "
        f"{{{{metric:ebitda_adjusted:{last}}}}} (margen {{{{metric:ebitda_adjusted_margin_pct:{last}}}}}), deuda neta / EBITDA "
        f"ajustado {{{{metric:net_debt_to_ebitda_adjusted:{last}}}}}.\n\n"
        + ("Principales riesgos:\n" + "\n".join(f"- {f.title} [[cite:{f.citations[0].citation_id}]]" for f in critical) + "\n\n" if critical else "")
        + "Puedo simular escenarios (ej. *¿qué pasa con el EBITDA si excluimos el arriendo pagado al socio?*) "
        "o buscar la fuente de un dato (ej. *¿de dónde sale el litigio laboral?*)."
    )
    answer = render_memo(template, base)
    return ChatResponse(answer_markdown=answer, citations=_resolve_citations(answer, index), mode="RULES")


def llm_answer(
    dossier: DealDossier,
    base: FinancialEngineResult,
    benchmarks: Mapping,
    message: str,
    llm: StructuredLLM,
    history: Sequence[dict],
) -> ChatResponse:
    index = dossier.citation_index()
    adjustments = "\n".join(
        f"- id={a.id} | {a.period} | {a.status} | {a.category} | {a.title} | {format_cop_millions(a.amount_cop)}"
        for a in dossier.ebitda_adjustments
    )
    flags = "\n".join(f"- {f.id} [{f.severity}/{f.status}] {f.title}" for f in dossier.red_flags)
    past = "\n".join(f"{h.get('role')}: {str(h.get('content'))[:600]}" for h in list(history)[-6:])
    user = (
        f"EXPEDIENTE: {dossier.company_name} (NIT {dossier.nit}, CIIU {dossier.ciiu_code})\n\n{engine_summary(base)}\n\n"
        f"{placeholder_catalog(base)}\n\nAJUSTES DE EBITDA:\n{adjustments}\n\nRED FLAGS:\n{flags}\n\n"
        f"{citation_catalog(list(index.values()), max_items=150)}\n\nCONVERSACIÓN PREVIA:\n{past or '(ninguna)'}\n\nPREGUNTA: {message}"
    )
    response = llm.complete_json(DOSSIER_CHAT, user, ChatLLMResponse, deal_id=dossier.deal_id, task="chat")
    valid_ids = {a.id for a in dossier.ebitda_adjustments}
    overrides = {k: v for k, v in response.scenario_overrides.items() if k in valid_ids}
    scenario: Optional[ScenarioResult] = None
    render_against = base
    answer = response.answer_markdown
    if overrides:
        titles = {a.id: a.title for a in dossier.ebitda_adjustments}
        scenario, render_against = _run_scenario(
            dossier, benchmarks, base, overrides, "; ".join(f"{titles[k]} → {v}" for k, v in overrides.items())
        )
        answer += f"\n\n**Recalculado por el motor determinista:**\n\n{scenario_table(scenario.before, scenario.after)}"
    answer = render_memo(answer, render_against)
    answer = CITATION_RE.sub(lambda m: m.group(0) if m.group(1) in index else "⟦cita no verificada⟧", answer)
    return ChatResponse(answer_markdown=answer, citations=_resolve_citations(answer, index), scenario=scenario, mode="LLM")


def answer_question(
    dossier: DealDossier,
    base: FinancialEngineResult,
    benchmarks: Mapping,
    message: str,
    llm: Optional[StructuredLLM] = None,
    history: Sequence[dict] = (),
) -> ChatResponse:
    if llm is not None:
        try:
            return llm_answer(dossier, base, benchmarks, message, llm, history)
        except LLMError:
            pass  # degradación controlada al enrutador determinista
    return rules_answer(dossier, base, benchmarks, message)
