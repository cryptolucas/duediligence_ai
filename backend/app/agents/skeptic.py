"""Nodo 4 — Agente Escéptico (Red Team).

Con LLM: ataca la tesis usando métricas del motor ya formateadas y documentos; cada red flag debe
tener al menos una cita verificada o se descarta.
Siempre: reglas deterministas que detectan señales duras (descuadres, deterioro de cartera, caída de
caja, apalancamiento sobre el P75 sectorial, contingencias, ítems ilegibles) y la información faltante
mínima para el Comité. En modo sin LLM son la única fuente de red flags.
"""

from __future__ import annotations

from typing import Optional, Sequence

from app.agents.context import AgentRuntime, NodeTimer, documents_context, engine_summary
from app.agents.llm_schemas import SkepticResponse
from app.agents.prompts import SKEPTIC_RED_TEAM
from app.schemas.deal import (
    CorporateProfile,
    EbitdaAdjustment,
    MappedAccountItem,
    MissingInfoItem,
    RedFlagItem,
    SourceCitation,
    SourceDocument,
    UnreadableItem,
)
from app.schemas.financials import FinancialEngineResult
from app.services.citation_guard import verify_quote
from app.services.llm_client import LLMError
from app.services.memo_renderer import format_cop_millions, format_days, format_multiple, format_pct

DSO_DETERIORATION_PCT = 15.0
CASH_DROP_PCT = 25.0
CRITICAL_CONTINGENCY_PCT_EBITDA = 25.0
_ALL_CATEGORIES = (
    "REVENUE", "COGS", "SGA", "DA", "OTHER_OP_INCOME_EXP", "NET_INTEREST", "TAXES", "CASH", "ACCOUNTS_RECEIVABLE",
    "INVENTORY", "OTHER_CURRENT_ASSETS", "PPE_AND_INTANGIBLES", "ACCOUNTS_PAYABLE", "SHORT_TERM_DEBT",
    "OTHER_CURRENT_LIABILITIES", "LONG_TERM_DEBT", "EQUITY",
)


def _cites(accounts: Sequence[MappedAccountItem], period: str, categories: Sequence[str], limit: int = 4) -> list[SourceCitation]:
    found = [a.citation for a in accounts if a.period == period and a.standard_category in categories]
    return found[:limit]


def rule_based_red_flags(
    result: FinancialEngineResult,
    accounts: Sequence[MappedAccountItem],
    profile: CorporateProfile,
    unreadable: Sequence[UnreadableItem],
) -> list[RedFlagItem]:
    flags: list[RedFlagItem] = []
    inc = {r.period: r for r in result.income_statement}
    wc = {r.period: r for r in result.working_capital}
    bal = {r.period: r for r in result.balance_sheet}
    lev = {r.period: r for r in result.leverage}
    periods = result.periods
    last = periods[-1]
    prev: Optional[str] = periods[-2] if len(periods) > 1 else None

    for b in result.balance_sheet:
        if not b.balance_check.is_balanced:
            cits = _cites(accounts, b.period, ["EQUITY", "CASH"]) or _cites(accounts, b.period, list(_ALL_CATEGORIES))
            if cits:
                flags.append(
                    RedFlagItem(
                        id=f"rf_rule_balance_{b.period}",
                        severity="HIGH",
                        domain="FINANCIAL",
                        title=f"El balance {b.period} no cuadra",
                        challenge_by_skeptic=(
                            f"Activo menos pasivo más patrimonio deja una diferencia de {format_cop_millions(b.balance_check.difference_cop)}. "
                            "Mientras no se explique, ninguna cifra del balance es confiable: puede haber cuentas omitidas o mal clasificadas."
                        ),
                        mitigation_question=f"¿Pueden enviar el balance de prueba {b.period} completo y cerrado, con todas las cuentas auxiliares?",
                        citations=cits,
                    )
                )

    if prev and wc[last].dso_days and wc[prev].dso_days and wc[last].dso_days > wc[prev].dso_days * (1 + DSO_DETERIORATION_PCT / 100):
        cits = _cites(accounts, last, ["ACCOUNTS_RECEIVABLE"]) + _cites(accounts, prev, ["ACCOUNTS_RECEIVABLE"], 2)
        if cits:
            flags.append(
                RedFlagItem(
                    id="rf_rule_cartera",
                    severity="HIGH",
                    domain="FINANCIAL",
                    title="La cartera se está cobrando más lento",
                    challenge_by_skeptic=(
                        f"Los días de cartera pasaron de {format_days(wc[prev].dso_days)} en {prev} a {format_days(wc[last].dso_days)} en {last}. "
                        "Crecer vendiendo a crédito más largo consume caja y puede esconder clientes con problemas de pago."
                    ),
                    mitigation_question=f"¿Cuál es la antigüedad de la cartera por cliente a cierre de {last} y qué clientes tienen pagos vencidos a más de 90 días?",
                    citations=cits,
                )
            )

    if prev and bal[prev].cash.value_cop > 0:
        drop = (1 - bal[last].cash.value_cop / bal[prev].cash.value_cop) * 100
        if drop >= CASH_DROP_PCT:
            cits = _cites(accounts, last, ["CASH"]) + _cites(accounts, prev, ["CASH"], 2)
            if cits:
                flags.append(
                    RedFlagItem(
                        id="rf_rule_caja",
                        severity="HIGH" if inc[last].net_income_cop > 0 else "MEDIUM",
                        domain="FINANCIAL",
                        title="La caja cae aunque la empresa reporta utilidades",
                        challenge_by_skeptic=(
                            f"El efectivo bajó de {format_cop_millions(bal[prev].cash.value_cop)} a {format_cop_millions(bal[last].cash.value_cop)} "
                            f"con una utilidad neta de {format_cop_millions(inc[last].net_income_cop)} en {last}. "
                            "Las utilidades no se están convirtiendo en caja: revisar capital de trabajo, dividendos y préstamos a socios."
                        ),
                        mitigation_question="¿En qué se usó la caja del año (dividendos, préstamos a socios, inversiones, pago de deuda)?",
                        citations=cits,
                    )
                )

    sector_leverage = result.valuation.sector_operating_benchmarks.get("net_debt_to_ebitda", {})
    nd_ebitda = lev[last].net_debt_to_ebitda_adjusted
    if nd_ebitda is not None and "p75" in sector_leverage and nd_ebitda > sector_leverage["p75"]:
        cits = _cites(accounts, last, ["SHORT_TERM_DEBT", "LONG_TERM_DEBT"])
        if cits:
            flags.append(
                RedFlagItem(
                    id="rf_rule_apalancamiento",
                    severity="HIGH",
                    domain="FINANCIAL",
                    title="Apalancamiento por encima del P75 del sector",
                    challenge_by_skeptic=(
                        f"Deuda neta / EBITDA ajustado de {format_multiple(nd_ebitda)} frente a un P75 sectorial de "
                        f"{format_multiple(sector_leverage['p75'])}. Hay poco espacio para deuda de adquisición y alto riesgo de covenants."
                    ),
                    mitigation_question="¿Qué covenants financieros tienen los créditos vigentes y cómo se calculan?",
                    citations=cits,
                )
            )

    revenue_cits = _cites(accounts, last, ["REVENUE"]) + _cites(accounts, prev, ["REVENUE"], 2) if prev else []
    if prev and revenue_cits and inc[prev].revenue.value_cop > 0 and inc[last].revenue.value_cop < inc[prev].revenue.value_cop:
        flags.append(
            RedFlagItem(
                id="rf_rule_ventas",
                severity="HIGH",
                domain="COMMERCIAL_MARKET",
                title="Los ingresos caen",
                challenge_by_skeptic=(
                    f"Los ingresos variaron {format_pct(inc[last].revenue_growth_yoy_pct)} en {last}. Una tesis de crecimiento "
                    "no se sostiene sin entender si es pérdida de clientes, precio o volumen."
                ),
                mitigation_question="¿Qué explica la caída de ventas (clientes perdidos, precios, volumen) y cómo va el año en curso?",
                citations=revenue_cits,
            )
        )

    c = result.contingencies
    procs = [p for p in profile.legal_proceedings if p.probability in ("PROBABLE", "POSIBLE")]
    if c.unprovisioned_probable_or_possible_cop > 0 and procs:
        pct = c.unprovisioned_pct_of_adjusted_ebitda
        flags.append(
            RedFlagItem(
                id="rf_rule_contingencias",
                severity="CRITICAL_DEALBREAKER" if pct is not None and pct >= CRITICAL_CONTINGENCY_PCT_EBITDA else "HIGH",
                domain="TAX_AND_CONTINGENCIES",
                title="Contingencias probables o posibles sin provisión",
                challenge_by_skeptic=(
                    f"Procesos sin provisión por {format_cop_millions(c.unprovisioned_probable_or_possible_cop)}, equivalentes a "
                    f"{format_pct(pct) or 'n/a'} del EBITDA ajustado. Sin indemnidad o escrow, el comprador hereda el pasivo."
                ),
                mitigation_question="¿Aceptarían los vendedores un escrow o una indemnidad específica por estos procesos?",
                citations=[p.citation for p in procs],
            )
        )

    readable_issues = [u for u in unreadable if u.citation is not None and u.id.startswith("unr_")]
    if readable_issues:  # todas traen citation (filtrado arriba)
        flags.append(
            RedFlagItem(
                id="rf_rule_ilegibles",
                severity="MEDIUM",
                domain="FINANCIAL",
                title="Hay datos que no se pudieron leer",
                challenge_by_skeptic=(
                    f"{len(readable_issues)} dato(s) quedaron ilegibles (errores de Excel o celdas con texto). No se imputaron valores: "
                    "si son materiales, los totales pueden estar incompletos."
                ),
                mitigation_question="¿Pueden reenviar el archivo con esas celdas corregidas o confirmar su valor?",
                citations=[u.citation for u in readable_issues[:5] if u.citation is not None],
            )
        )
    return [f for f in flags if f.citations]


def rule_based_missing_info(
    documents: Sequence[SourceDocument],
    profile: CorporateProfile,
    result: FinancialEngineResult,
    adjustments: Sequence[EbitdaAdjustment],
    unreadable: Sequence[UnreadableItem],
) -> list[MissingInfoItem]:
    types = {d.document_type for d in documents}
    items: list[MissingInfoItem] = []

    def add(item_id, category, request, why, priority="MUST_HAVE_FOR_IC"):
        items.append(
            MissingInfoItem(
                id=item_id,
                category=category,
                requested_document_or_clarification=request,
                why_it_matters_plain_spanish=why,
                priority=priority,
            )
        )

    if "CHAMBER_OF_COMMERCE_CERT" not in types:
        add("mi_rule_camara", "Societario", "Certificado de existencia y representación legal con vigencia menor a 30 días.",
            "Nos confirma quién representa legalmente a la empresa y qué decisiones necesitan autorización de los socios.")
    if "FINANCIAL_STATEMENTS_PDF" not in types:
        add("mi_rule_eeff", "Financiero", "Estados financieros dictaminados con sus notas de los últimos tres años.",
            "Las notas explican el detalle de los números (deudas, litigios, partes relacionadas) y nos evitan sorpresas.")
    if len(result.periods) < 3:
        add("mi_rule_periodos", "Financiero", "Balances de prueba de los últimos tres cierres anuales.",
            "Con tres años podemos ver la tendencia real del negocio y no solo una foto de un año.")
    if not any(s.verification_status == "VERIFIED" for s in profile.shareholders):
        add("mi_rule_accionistas", "Societario", "Libro de registro de accionistas y acuerdos de accionistas vigentes.",
            "Necesitamos confirmar quiénes son los dueños y que las acciones estén libres de prendas o restricciones.")
    if not adjustments:
        add("mi_rule_partes_relacionadas", "Calidad del EBITDA",
            "Detalle de pagos a socios y familiares (sueldos, arriendos, préstamos) y gastos no recurrentes de los últimos tres años.",
            "Nos permite separar lo que es costo real del negocio de lo que son gastos de los dueños, para valorar justo la empresa.")
    if any(u.citation is not None for u in unreadable):
        add("mi_rule_ilegibles", "Calidad de datos", "Versión corregida de los archivos con celdas ilegibles o valores en texto.",
            "Algunos datos no se pudieron leer; con el archivo corregido evitamos supuestos.", "NICE_TO_HAVE")
    add("mi_rule_creditos", "Financiero", "Contratos de crédito y leasing vigentes con sus covenants.",
        "Queremos asegurarnos de que la entrada de un socio no active cláusulas que obliguen a pagar los créditos de inmediato.",
        "NICE_TO_HAVE")
    return items


def _llm_flags(state: dict, runtime: AgentRuntime, notes: list[str]) -> tuple[list[RedFlagItem], list[MissingInfoItem]]:
    documents = state["documents"]
    result: FinancialEngineResult = state["financials"]
    adjustments = state["ebitda_adjustments"]
    profile: CorporateProfile = state["corporate_profile"]
    adj_text = "\n".join(
        f"- {a.id} [{a.status}] {a.period} {a.title}: {format_cop_millions(a.amount_cop)}" for a in adjustments
    ) or "(sin ajustes)"
    procs = "\n".join(f"- {p.proceeding_type} {p.probability}: {p.description}" for p in profile.legal_proceedings) or "(sin litigios)"
    user = (
        f"EMPRESA: {state['company']['company_name']} (CIIU {state['company']['ciiu_code']})\n\n"
        f"{engine_summary(result)}\n\nAJUSTES DE EBITDA:\n{adj_text}\n\nLITIGIOS:\n{procs}\n\n"
        f"DOCUMENTOS:\n{documents_context(documents, max_chars=50_000)}"
    )
    response = runtime.llm.complete_json(  # type: ignore[union-attr]
        SKEPTIC_RED_TEAM, user, SkepticResponse, deal_id=runtime.deal_id, task="skeptic"
    )
    flags: list[RedFlagItem] = []
    dropped: list[str] = []
    for n, prop in enumerate(response.red_flags, start=1):
        citations = []
        for ev in prop.evidence:
            verified = verify_quote(documents, ev.document_id, ev.page_or_sheet, ev.exact_quote, 0.85).citation
            if verified is not None and verified.citation_id not in {c.citation_id for c in citations}:
                citations.append(verified)
        if not citations:
            dropped.append(prop.title)
            continue
        flags.append(
            RedFlagItem(
                id=f"rf_ai_{n:02d}",
                severity=prop.severity,
                domain=prop.domain,
                title=prop.title,
                challenge_by_skeptic=prop.challenge_by_skeptic,
                mitigation_question=prop.mitigation_question,
                citations=citations,
            )
        )
    if dropped:
        notes.append("Red flags descartadas por no tener evidencia literal verificable: " + "; ".join(dropped))
    missing = [
        MissingInfoItem(id=f"mi_ai_{n:02d}", **item.model_dump()) for n, item in enumerate(response.missing_info, start=1)
    ]
    return flags, missing


HARD_RULE_IDS = ("rf_rule_balance_", "rf_rule_ilegibles", "rf_rule_contingencias")


def run_skeptic(state: dict, runtime: AgentRuntime) -> dict:
    timer = NodeTimer("node_skeptic_red_team", runtime.effective_mode)
    calls_before = getattr(runtime.llm, "calls", 0)
    notes: list[str] = []
    result: FinancialEngineResult = state["financials"]
    rule_flags = rule_based_red_flags(result, state["mapped_accounts"], state["corporate_profile"], state["unreadable_items"])
    rule_missing = rule_based_missing_info(
        state["documents"], state["corporate_profile"], result, state["ebitda_adjustments"], state["unreadable_items"]
    )
    flags, missing = rule_flags, rule_missing
    if runtime.uses_llm:
        try:
            ai_flags, ai_missing = _llm_flags(state, runtime, notes)
            # Con LLM se conservan solo las reglas "duras" (descuadres, ilegibles, contingencias) para no duplicar temas.
            flags = ai_flags + [f for f in rule_flags if f.id.startswith(HARD_RULE_IDS)]
            missing = ai_missing + [m for m in rule_missing if m.id in ("mi_rule_camara", "mi_rule_eeff", "mi_rule_periodos")]
        except LLMError as exc:
            notes.append(f"Fallo del LLM escéptico ({exc}); se usan solo reglas deterministas.")
    severity_order = {"CRITICAL_DEALBREAKER": 0, "HIGH": 1, "MEDIUM": 2}
    flags.sort(key=lambda f: severity_order[f.severity])
    missing.sort(key=lambda m: 0 if m.priority == "MUST_HAVE_FOR_IC" else 1)
    return {
        "red_flags": flags,
        "missing_info": missing,
        "processing_log": [
            timer.entry(
                f"{len(flags)} red flag(s) y {len(missing)} solicitud(es) de información.",
                llm_calls=getattr(runtime.llm, "calls", 0) - calls_before,
                notes=notes,
            )
        ],
    }
