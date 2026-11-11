"""Motor financiero 100 % determinista (CERO LLM).

Este módulo concentra TODA la aritmética del expediente: agregación por categoría, márgenes,
crecimiento YoY/CAGR, puente de EBITDA, capital de trabajo, apalancamiento, validación de la
ecuación contable y valoración por múltiplos sectoriales.

Reglas de diseño:
* Solo depende de la librería estándar y de los esquemas Pydantic del proyecto. Un test verifica
  que no importe ningún cliente de LLM.
* Funciones puras: misma entrada -> misma salida. No muta los objetos recibidos.
* Divisiones por cero o bases no positivas devuelven ``None`` (no calculable), nunca un número inventado.
* Sumas con ``math.fsum`` para evitar deriva de punto flotante.
* Recalcular un expediente completo toma ~1 ms; el requisito del sandbox interactivo es < 100 ms.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Iterable, Mapping, Optional, Sequence

from app.schemas.deal import (
    ASSET_CATEGORIES,
    EQUITY_CATEGORIES,
    LIABILITY_CATEGORIES,
    DealDossier,
    EbitdaAdjustment,
    LegalProceeding,
    MappedAccountItem,
)
from app.schemas.financials import (
    BalanceCheck,
    BalanceSheetMetrics,
    BridgeLine,
    ContingencyExposure,
    EbitdaBridge,
    EngineWarning,
    FinancialEngineResult,
    GrowthSummary,
    IncomeStatementMetrics,
    LeverageMetrics,
    TracedValue,
    ValuationResult,
    ValuationScenario,
    WorkingCapitalMetrics,
)

ENGINE_VERSION = "1.0.0"
DEFAULT_BALANCE_TOLERANCE_COP = 1_000.0
DAYS_IN_YEAR = 365.0

SCENARIO_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("CONSERVADOR", "P25", "p25"),
    ("BASE", "MEDIANA", "median"),
    ("OPTIMISTA", "P75", "p75"),
)
CONTINGENCY_PROBABILITIES_AT_RISK = frozenset({"PROBABLE", "POSIBLE"})


# ---------------------------------------------------------------------------
# Primitivas aritméticas
# ---------------------------------------------------------------------------


def fsum(values: Iterable[float]) -> float:
    return math.fsum(values)


def safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """División que devuelve None si el denominador es cero o algún operando falta."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    ratio = safe_div(numerator, denominator)
    return None if ratio is None else ratio * 100.0


def growth_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Crecimiento YoY en %. No calculable si la base es nula o no positiva."""
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def cagr_pct(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    """Tasa de crecimiento anual compuesta en %. Requiere valores positivos y al menos un año."""
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1.0 / years) - 1.0) * 100.0


def days_metric(balance: Optional[float], flow: Optional[float]) -> Optional[float]:
    """Días de rotación: saldo / flujo anual * 365. No calculable si el flujo no es positivo."""
    if balance is None or flow is None or flow <= 0:
        return None
    return balance / flow * DAYS_IN_YEAR


# ---------------------------------------------------------------------------
# Agregación trazable
# ---------------------------------------------------------------------------


class CategoryLedger:
    """Totales por (periodo, categoría) que conservan las citas de las cuentas que los componen."""

    def __init__(self, accounts: Sequence[MappedAccountItem]):
        values: dict[tuple[str, str], list[float]] = defaultdict(list)
        citations: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.unmapped: list[MappedAccountItem] = []
        for item in accounts:
            if item.standard_category == "UNMAPPED":
                self.unmapped.append(item)
                continue
            key = (item.period, item.standard_category)
            values[key].append(item.raw_value_cop)
            citations[key].append(item.citation.citation_id)
        self._values = values
        self._citations = citations
        self.periods_with_data = {period for period, _ in values}

    def traced(self, period: str, *categories: str) -> TracedValue:
        vals: list[float] = []
        cits: list[str] = []
        for category in categories:
            vals.extend(self._values.get((period, category), ()))
            cits.extend(self._citations.get((period, category), ()))
        return TracedValue(value_cop=fsum(vals), source_citation_ids=cits)

    def value(self, period: str, *categories: str) -> float:
        return self.traced(period, *categories).value_cop

    def has(self, period: str, category: str) -> bool:
        return (period, category) in self._values


# ---------------------------------------------------------------------------
# Ajustes de EBITDA (sandbox humano en el circuito)
# ---------------------------------------------------------------------------


def apply_adjustment_overrides(
    adjustments: Sequence[EbitdaAdjustment],
    status_overrides: Optional[Mapping[str, str]] = None,
    manual_adjustments: Optional[Sequence[EbitdaAdjustment]] = None,
) -> list[EbitdaAdjustment]:
    """Devuelve una NUEVA lista de ajustes con los toggles del analista aplicados.

    * ``status_overrides``: {adjustment_id: "ACCEPTED" | "REJECTED" | "PENDING_REVIEW"}.
    * ``manual_adjustments``: ajustes agregados por el analista (se fuerza ``origin='ANALYST_MANUAL'``).
    Lanza ``ValueError`` si un override apunta a un id inexistente o un manual repite un id.
    """
    overrides = dict(status_overrides or {})
    valid_status = {"ACCEPTED", "REJECTED", "PENDING_REVIEW"}
    result: list[EbitdaAdjustment] = []
    known_ids: set[str] = set()
    for adj in adjustments:
        known_ids.add(adj.id)
        if adj.id in overrides:
            new_status = overrides.pop(adj.id)
            if new_status not in valid_status:
                raise ValueError(f"Estado inválido '{new_status}' para el ajuste {adj.id}.")
            result.append(adj.model_copy(update={"status": new_status}))
        else:
            result.append(adj.model_copy())
    for manual in manual_adjustments or ():
        if manual.id in known_ids:
            raise ValueError(f"El ajuste manual {manual.id} repite un id existente.")
        known_ids.add(manual.id)
        new_status = overrides.pop(manual.id, manual.status)
        if new_status not in valid_status:
            raise ValueError(f"Estado inválido '{new_status}' para el ajuste {manual.id}.")
        result.append(manual.model_copy(update={"origin": "ANALYST_MANUAL", "status": new_status}))
    if overrides:
        raise ValueError(f"Overrides para ajustes inexistentes: {sorted(overrides)}")
    return result


def build_ebitda_bridge(period: str, ebitda_reported: float, adjustments: Sequence[EbitdaAdjustment]) -> EbitdaBridge:
    """Puente EBITDA reportado -> ajustado. Solo los ajustes ACCEPTED modifican el EBITDA."""
    lines: list[BridgeLine] = []
    accepted: list[float] = []
    pending: list[float] = []
    rejected: list[float] = []
    for adj in adjustments:
        if adj.period != period:
            continue
        included = adj.status == "ACCEPTED"
        {"ACCEPTED": accepted, "PENDING_REVIEW": pending, "REJECTED": rejected}[adj.status].append(adj.amount_cop)
        lines.append(
            BridgeLine(
                adjustment_id=adj.id,
                title=adj.title,
                category=adj.category,
                amount_cop=adj.amount_cop,
                status=adj.status,
                included=included,
                origin=adj.origin,
                citation_id=adj.citation.citation_id,
            )
        )
    total_accepted = fsum(accepted)
    return EbitdaBridge(
        period=period,
        ebitda_reported_cop=ebitda_reported,
        lines=lines,
        total_accepted_adjustments_cop=total_accepted,
        total_pending_adjustments_cop=fsum(pending),
        total_rejected_adjustments_cop=fsum(rejected),
        ebitda_adjusted_cop=fsum([ebitda_reported, total_accepted]),
    )


# ---------------------------------------------------------------------------
# Estados financieros
# ---------------------------------------------------------------------------


def build_income_statement(
    ledger: CategoryLedger,
    period: str,
    previous_period: Optional[str],
    ebitda_adjusted: float,
) -> IncomeStatementMetrics:
    revenue = ledger.traced(period, "REVENUE")
    cogs = ledger.traced(period, "COGS")
    sga = ledger.traced(period, "SGA")
    other = ledger.traced(period, "OTHER_OP_INCOME_EXP")
    da = ledger.traced(period, "DA")
    interest = ledger.traced(period, "NET_INTEREST")
    taxes = ledger.traced(period, "TAXES")

    gross_profit = revenue.value_cop - cogs.value_cop
    ebitda = fsum([gross_profit, -sga.value_cop, other.value_cop])
    ebit = ebitda - da.value_cop
    pre_tax = ebit - interest.value_cop
    net_income = pre_tax - taxes.value_cop
    previous_revenue = ledger.value(previous_period, "REVENUE") if previous_period else None

    return IncomeStatementMetrics(
        period=period,
        revenue=revenue,
        cogs=cogs,
        gross_profit_cop=gross_profit,
        sga=sga,
        other_operating_income_expense=other,
        ebitda_reported_cop=ebitda,
        depreciation_amortization=da,
        ebit_cop=ebit,
        net_interest=interest,
        pre_tax_income_cop=pre_tax,
        taxes=taxes,
        net_income_cop=net_income,
        revenue_growth_yoy_pct=growth_pct(revenue.value_cop, previous_revenue),
        gross_margin_pct=pct(gross_profit, revenue.value_cop),
        ebitda_reported_margin_pct=pct(ebitda, revenue.value_cop),
        ebitda_adjusted_cop=ebitda_adjusted,
        ebitda_adjusted_margin_pct=pct(ebitda_adjusted, revenue.value_cop),
        net_margin_pct=pct(net_income, revenue.value_cop),
    )


def compute_reported_ebitda(ledger: CategoryLedger, period: str) -> float:
    return fsum(
        [
            ledger.value(period, "REVENUE"),
            -ledger.value(period, "COGS"),
            -ledger.value(period, "SGA"),
            ledger.value(period, "OTHER_OP_INCOME_EXP"),
        ]
    )


def check_balance(
    period: str,
    total_assets: float,
    total_liabilities: float,
    total_equity: float,
    tolerance_cop: float = DEFAULT_BALANCE_TOLERANCE_COP,
    current_year_result_cop: float = 0.0,
) -> BalanceCheck:
    """Valida la ecuación contable Activo == Pasivo + Patrimonio dentro de una tolerancia absoluta.

    ``current_year_result_cop`` se usa solo con balances de prueba pre-cierre, donde el resultado
    del ejercicio aún vive en las cuentas de resultado y no en el patrimonio (3605).
    """
    equity = fsum([total_equity, current_year_result_cop])
    difference = fsum([total_assets, -total_liabilities, -equity])
    return BalanceCheck(
        period=period,
        total_assets_cop=total_assets,
        total_liabilities_cop=total_liabilities,
        total_equity_cop=equity,
        current_year_result_included_cop=current_year_result_cop,
        difference_cop=difference,
        is_balanced=abs(difference) <= tolerance_cop,
        tolerance_cop=tolerance_cop,
    )


def build_balance_sheet(
    ledger: CategoryLedger,
    period: str,
    tolerance_cop: float,
    current_year_result_cop: float = 0.0,
) -> BalanceSheetMetrics:
    cash = ledger.traced(period, "CASH")
    ar = ledger.traced(period, "ACCOUNTS_RECEIVABLE")
    inventory = ledger.traced(period, "INVENTORY")
    oca = ledger.traced(period, "OTHER_CURRENT_ASSETS")
    ppe = ledger.traced(period, "PPE_AND_INTANGIBLES")
    ap = ledger.traced(period, "ACCOUNTS_PAYABLE")
    std = ledger.traced(period, "SHORT_TERM_DEBT")
    ocl = ledger.traced(period, "OTHER_CURRENT_LIABILITIES")
    ltd = ledger.traced(period, "LONG_TERM_DEBT")
    equity = ledger.traced(period, *EQUITY_CATEGORIES)

    total_current_assets = fsum([cash.value_cop, ar.value_cop, inventory.value_cop, oca.value_cop])
    total_assets = ledger.value(period, *ASSET_CATEGORIES)
    total_current_liabilities = fsum([ap.value_cop, std.value_cop, ocl.value_cop])
    total_liabilities = ledger.value(period, *LIABILITY_CATEGORIES)

    return BalanceSheetMetrics(
        period=period,
        cash=cash,
        accounts_receivable=ar,
        inventory=inventory,
        other_current_assets=oca,
        ppe_and_intangibles=ppe,
        total_current_assets_cop=total_current_assets,
        total_assets_cop=total_assets,
        accounts_payable=ap,
        short_term_debt=std,
        other_current_liabilities=ocl,
        long_term_debt=ltd,
        total_current_liabilities_cop=total_current_liabilities,
        total_liabilities_cop=total_liabilities,
        equity=equity,
        balance_check=check_balance(
            period, total_assets, total_liabilities, equity.value_cop, tolerance_cop, current_year_result_cop
        ),
    )


def compute_working_capital(income: IncomeStatementMetrics, balance: BalanceSheetMetrics) -> WorkingCapitalMetrics:
    """Capital de trabajo neto operativo = CxC + Inventarios - CxP, más días de rotación."""
    ar = balance.accounts_receivable.value_cop
    inv = balance.inventory.value_cop
    ap = balance.accounts_payable.value_cop
    nwc = fsum([ar, inv, -ap])
    revenue = income.revenue.value_cop
    cogs = income.cogs.value_cop
    dso = days_metric(ar, revenue)
    dio = days_metric(inv, cogs)
    dpo = days_metric(ap, cogs)
    ccc = None if None in (dso, dio, dpo) else fsum([dso, dio, -dpo])  # type: ignore[list-item]
    return WorkingCapitalMetrics(
        period=income.period,
        net_working_capital_cop=nwc,
        nwc_pct_of_revenue=pct(nwc, revenue) if revenue > 0 else None,
        dso_days=dso,
        dio_days=dio,
        dpo_days=dpo,
        cash_conversion_cycle_days=ccc,
        current_ratio=safe_div(balance.total_current_assets_cop, balance.total_current_liabilities_cop),
    )


def leverage_ratio(net_debt: float, ebitda: float) -> Optional[float]:
    """Deuda neta / EBITDA. No significativo (None) si el EBITDA no es positivo."""
    if ebitda <= 0:
        return None
    return net_debt / ebitda


def compute_leverage(income: IncomeStatementMetrics, balance: BalanceSheetMetrics) -> LeverageMetrics:
    gross_debt = fsum([balance.short_term_debt.value_cop, balance.long_term_debt.value_cop])
    net_debt = fsum([gross_debt, -balance.cash.value_cop])
    net_interest = income.net_interest.value_cop
    return LeverageMetrics(
        period=income.period,
        gross_financial_debt_cop=gross_debt,
        net_financial_debt_cop=net_debt,
        net_debt_to_ebitda_reported=leverage_ratio(net_debt, income.ebitda_reported_cop),
        net_debt_to_ebitda_adjusted=leverage_ratio(net_debt, income.ebitda_adjusted_cop),
        interest_coverage_ebitda_adjusted=safe_div(income.ebitda_adjusted_cop, net_interest) if net_interest > 0 else None,
    )


# ---------------------------------------------------------------------------
# Valoración por múltiplos sectoriales
# ---------------------------------------------------------------------------


def resolve_sector(benchmarks: Mapping, ciiu_code: str) -> tuple[Optional[str], Optional[dict]]:
    """Busca el sector por código CIIU exacto y, si no existe, por división (2 primeros dígitos)."""
    code = (ciiu_code or "").strip()
    catalog = benchmarks.get("ciiu_catalog", {})
    sectors = benchmarks.get("sectors", {})
    sector_key = catalog.get(code, {}).get("sector_key")
    if sector_key is None and len(code) >= 2:
        sector_key = benchmarks.get("ciiu_division_fallback", {}).get(code[:2])
    if sector_key is None or sector_key not in sectors:
        return None, None
    return sector_key, sectors[sector_key]


def compute_valuation(
    ciiu_code: str,
    benchmarks: Mapping,
    valuation_period: str,
    ebitda_adjusted: float,
    net_debt: float,
    revenue: float,
) -> ValuationResult:
    """EV = múltiplo EV/EBITDA sectorial x EBITDA ajustado; Equity = EV - Deuda financiera neta."""
    sector_key, sector = resolve_sector(benchmarks, ciiu_code)
    benchmark_status = benchmarks.get("_meta", {}).get("status")
    if sector is None:
        return ValuationResult(
            status="MISSING_DATA",
            valuation_period=valuation_period,
            ciiu_code=ciiu_code,
            sector_key=None,
            sector_label=None,
            benchmark_status=benchmark_status,
            ebitda_basis_cop=ebitda_adjusted,
            scenarios=[],
            message=f"No hay benchmark sectorial para el CIIU {ciiu_code}.",
        )
    operating = {name: dict(stats) for name, stats in sector.get("operating_benchmarks", {}).items()}
    if ebitda_adjusted <= 0:
        return ValuationResult(
            status="NOT_MEANINGFUL",
            valuation_period=valuation_period,
            ciiu_code=ciiu_code,
            sector_key=sector_key,
            sector_label=sector.get("label"),
            benchmark_status=benchmark_status,
            ebitda_basis_cop=ebitda_adjusted,
            scenarios=[],
            sector_operating_benchmarks=operating,
            message="EBITDA ajustado no positivo: la valoración por múltiplos EV/EBITDA no es significativa.",
        )
    multiples = sector["ev_ebitda"]
    scenarios = []
    for scenario, percentile, key in SCENARIO_DEFINITIONS:
        multiple = float(multiples[key])
        ev = multiple * ebitda_adjusted
        scenarios.append(
            ValuationScenario(
                scenario=scenario,  # type: ignore[arg-type]
                percentile=percentile,  # type: ignore[arg-type]
                ev_ebitda_multiple=multiple,
                enterprise_value_cop=ev,
                net_financial_debt_cop=net_debt,
                equity_value_cop=ev - net_debt,
                implied_ev_revenue=safe_div(ev, revenue) if revenue > 0 else None,
            )
        )
    return ValuationResult(
        status="OK",
        valuation_period=valuation_period,
        ciiu_code=ciiu_code,
        sector_key=sector_key,
        sector_label=sector.get("label"),
        benchmark_status=benchmark_status,
        ebitda_basis_cop=ebitda_adjusted,
        scenarios=scenarios,
        sector_operating_benchmarks=operating,
    )


def compute_contingency_exposure(
    proceedings: Sequence[LegalProceeding],
    ebitda_adjusted: float,
    base_equity_value: Optional[float],
) -> ContingencyExposure:
    """Exposición no provisionada = Σ max(pretensión - provisión, 0) de procesos probables o posibles."""
    claimed: list[float] = []
    provisioned: list[float] = []
    at_risk: list[float] = []
    ids: list[str] = []
    for proc in proceedings:
        ids.append(proc.id)
        provisioned.append(proc.provisioned_amount_cop)
        if proc.claimed_amount_cop is None:
            continue
        claimed.append(proc.claimed_amount_cop)
        if proc.probability in CONTINGENCY_PROBABILITIES_AT_RISK:
            at_risk.append(max(proc.claimed_amount_cop - proc.provisioned_amount_cop, 0.0))
    unprovisioned = fsum(at_risk)
    return ContingencyExposure(
        total_claimed_cop=fsum(claimed),
        total_provisioned_cop=fsum(provisioned),
        unprovisioned_probable_or_possible_cop=unprovisioned,
        unprovisioned_pct_of_adjusted_ebitda=pct(unprovisioned, ebitda_adjusted) if ebitda_adjusted > 0 else None,
        unprovisioned_pct_of_base_equity_value=(
            pct(unprovisioned, base_equity_value) if base_equity_value is not None and base_equity_value > 0 else None
        ),
        proceeding_ids=ids,
    )


# ---------------------------------------------------------------------------
# Orquestación del motor
# ---------------------------------------------------------------------------


def run_financial_engine(
    accounts: Sequence[MappedAccountItem],
    adjustments: Sequence[EbitdaAdjustment],
    ciiu_code: str,
    benchmarks: Mapping,
    legal_proceedings: Sequence[LegalProceeding] = (),
    periods: Optional[Sequence[str]] = None,
    balance_tolerance_cop: float = DEFAULT_BALANCE_TOLERANCE_COP,
    pre_closing_periods: Sequence[str] = (),
) -> FinancialEngineResult:
    """Ejecuta todos los cálculos deterministas del expediente y devuelve un resultado completo."""
    pre_closing = set(pre_closing_periods)
    started = time.perf_counter()
    ledger = CategoryLedger(accounts)
    ordered_periods = sorted(set(periods) if periods else {a.period for a in accounts})
    if not ordered_periods:
        raise ValueError("No hay periodos para calcular.")
    unknown = {a.period for a in adjustments} - set(ordered_periods)
    if unknown:
        raise ValueError(f"Ajustes con periodos fuera del análisis: {sorted(unknown)}")

    warnings: list[EngineWarning] = []
    income_rows: list[IncomeStatementMetrics] = []
    balance_rows: list[BalanceSheetMetrics] = []
    wc_rows: list[WorkingCapitalMetrics] = []
    leverage_rows: list[LeverageMetrics] = []
    bridges: list[EbitdaBridge] = []

    previous: Optional[str] = None
    for period in ordered_periods:
        if period not in ledger.periods_with_data or not ledger.has(period, "REVENUE"):
            warnings.append(
                EngineWarning(code="MISSING_PERIOD_DATA", period=period, message=f"Sin ingresos mapeados para {period}.")
            )
        ebitda_reported = compute_reported_ebitda(ledger, period)
        bridge = build_ebitda_bridge(period, ebitda_reported, adjustments)
        income = build_income_statement(ledger, period, previous, bridge.ebitda_adjusted_cop)
        balance = build_balance_sheet(
            ledger,
            period,
            balance_tolerance_cop,
            income.net_income_cop if period in pre_closing else 0.0,
        )
        bridges.append(bridge)
        income_rows.append(income)
        balance_rows.append(balance)
        wc_rows.append(compute_working_capital(income, balance))
        leverage_rows.append(compute_leverage(income, balance))

        check = balance.balance_check
        if not check.is_balanced:
            warnings.append(
                EngineWarning(
                    code="BALANCE_MISMATCH",
                    period=period,
                    message=(
                        f"Descuadre contable en {period}: Activo - (Pasivo + Patrimonio) = "
                        f"{check.difference_cop:,.0f} COP (tolerancia {check.tolerance_cop:,.0f})."
                    ),
                )
            )
        if bridge.ebitda_adjusted_cop <= 0:
            warnings.append(
                EngineWarning(
                    code="NON_POSITIVE_EBITDA",
                    period=period,
                    message=f"EBITDA ajustado no positivo en {period}: múltiplos de deuda y valoración no significativos.",
                )
            )
        previous = period

    if ledger.unmapped:
        unmapped_periods = sorted({item.period for item in ledger.unmapped})
        warnings.append(
            EngineWarning(
                code="UNMAPPED_ACCOUNTS",
                message=(
                    f"{len(ledger.unmapped)} cuenta(s) UNMAPPED excluidas de los cálculos "
                    f"(periodos: {', '.join(unmapped_periods)})."
                ),
            )
        )

    first, last = income_rows[0], income_rows[-1]
    years = len(ordered_periods) - 1
    growth = GrowthSummary(
        first_period=first.period,
        last_period=last.period,
        revenue_cagr_pct=cagr_pct(first.revenue.value_cop, last.revenue.value_cop, years),
        ebitda_adjusted_cagr_pct=cagr_pct(first.ebitda_adjusted_cop, last.ebitda_adjusted_cop, years),
    )

    last_leverage = leverage_rows[-1]
    valuation = compute_valuation(
        ciiu_code=ciiu_code,
        benchmarks=benchmarks,
        valuation_period=last.period,
        ebitda_adjusted=last.ebitda_adjusted_cop,
        net_debt=last_leverage.net_financial_debt_cop,
        revenue=last.revenue.value_cop,
    )
    if valuation.status == "MISSING_DATA":
        warnings.append(EngineWarning(code="MISSING_BENCHMARK", message=valuation.message or "Sin benchmark."))

    base_equity = next((s.equity_value_cop for s in valuation.scenarios if s.scenario == "BASE"), None)
    contingencies = compute_contingency_exposure(legal_proceedings, last.ebitda_adjusted_cop, base_equity)

    return FinancialEngineResult(
        engine_version=ENGINE_VERSION,
        llm_calls=0,
        periods=list(ordered_periods),
        income_statement=income_rows,
        balance_sheet=balance_rows,
        working_capital=wc_rows,
        leverage=leverage_rows,
        ebitda_bridge=bridges,
        growth=growth,
        valuation=valuation,
        contingencies=contingencies,
        unmapped_account_count=len(ledger.unmapped),
        warnings=warnings,
        computation_ms=(time.perf_counter() - started) * 1000.0,
    )


def recalculate_dossier(
    dossier: DealDossier,
    benchmarks: Mapping,
    status_overrides: Optional[Mapping[str, str]] = None,
    manual_adjustments: Optional[Sequence[EbitdaAdjustment]] = None,
    balance_tolerance_cop: float = DEFAULT_BALANCE_TOLERANCE_COP,
) -> tuple[list[EbitdaAdjustment], FinancialEngineResult]:
    """Punto de entrada del sandbox: aplica toggles del analista y recalcula todo sin llamar a un LLM."""
    adjustments = apply_adjustment_overrides(dossier.ebitda_adjustments, status_overrides, manual_adjustments)
    result = run_financial_engine(
        accounts=dossier.mapped_accounts,
        adjustments=adjustments,
        ciiu_code=dossier.ciiu_code,
        benchmarks=benchmarks,
        legal_proceedings=dossier.corporate_profile.legal_proceedings,
        periods=dossier.periods,
        balance_tolerance_cop=balance_tolerance_cop,
        pre_closing_periods=dossier.pre_closing_trial_balance_periods,
    )
    return adjustments, result


def convert_cop(value_cop: Optional[float], unit: str, cop_per_usd: Optional[float] = None) -> Optional[float]:
    """Conversión de presentación: 'COP', 'COP_MILLONES' o 'USD' (requiere TRM COP/USD > 0)."""
    if value_cop is None:
        return None
    if unit == "COP":
        return value_cop
    if unit == "COP_MILLONES":
        return value_cop / 1_000_000.0
    if unit == "USD":
        if cop_per_usd is None or cop_per_usd <= 0:
            raise ValueError("Se requiere una TRM (COP por USD) positiva para convertir a USD.")
        return value_cop / cop_per_usd
    raise ValueError(f"Unidad no soportada: {unit}")
