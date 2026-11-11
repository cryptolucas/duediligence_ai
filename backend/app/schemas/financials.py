"""Esquemas de salida del motor financiero determinista.

Todos los valores monetarios están en COP plenos. Los porcentajes se expresan en puntos
porcentuales (9.55 = 9,55 %). Un valor ``None`` significa "no calculable" (división por cero,
periodo base inexistente o dato faltante) y viene acompañado de una advertencia en ``warnings``.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TracedValue(BaseModel):
    """Cifra agregada por el motor con la lista de citas de las cuentas que la componen."""

    value_cop: float
    source_citation_ids: List[str] = Field(default_factory=list)


class IncomeStatementMetrics(BaseModel):
    period: str
    revenue: TracedValue
    cogs: TracedValue
    gross_profit_cop: float
    sga: TracedValue
    other_operating_income_expense: TracedValue
    ebitda_reported_cop: float
    depreciation_amortization: TracedValue
    ebit_cop: float
    net_interest: TracedValue
    pre_tax_income_cop: float
    taxes: TracedValue
    net_income_cop: float
    revenue_growth_yoy_pct: Optional[float]
    gross_margin_pct: Optional[float]
    ebitda_reported_margin_pct: Optional[float]
    ebitda_adjusted_cop: float
    ebitda_adjusted_margin_pct: Optional[float]
    net_margin_pct: Optional[float]


class BalanceCheck(BaseModel):
    period: str
    total_assets_cop: float
    total_liabilities_cop: float
    total_equity_cop: float
    current_year_result_included_cop: float = Field(
        0.0, description="Resultado del ejercicio sumado al patrimonio cuando el balance de prueba es pre-cierre."
    )
    difference_cop: float = Field(..., description="Activo - (Pasivo + Patrimonio).")
    is_balanced: bool
    tolerance_cop: float


class BalanceSheetMetrics(BaseModel):
    period: str
    cash: TracedValue
    accounts_receivable: TracedValue
    inventory: TracedValue
    other_current_assets: TracedValue
    ppe_and_intangibles: TracedValue
    total_current_assets_cop: float
    total_assets_cop: float
    accounts_payable: TracedValue
    short_term_debt: TracedValue
    other_current_liabilities: TracedValue
    long_term_debt: TracedValue
    total_current_liabilities_cop: float
    total_liabilities_cop: float
    equity: TracedValue
    balance_check: BalanceCheck


class WorkingCapitalMetrics(BaseModel):
    period: str
    net_working_capital_cop: float = Field(..., description="CxC + Inventarios - CxP.")
    nwc_pct_of_revenue: Optional[float]
    dso_days: Optional[float] = Field(None, description="CxC / Ingresos * 365.")
    dio_days: Optional[float] = Field(None, description="Inventarios / Costo de ventas * 365.")
    dpo_days: Optional[float] = Field(None, description="CxP / Costo de ventas * 365.")
    cash_conversion_cycle_days: Optional[float]
    current_ratio: Optional[float]


class LeverageMetrics(BaseModel):
    period: str
    gross_financial_debt_cop: float
    net_financial_debt_cop: float = Field(..., description="Deuda CP + Deuda LP - Caja.")
    net_debt_to_ebitda_reported: Optional[float]
    net_debt_to_ebitda_adjusted: Optional[float]
    interest_coverage_ebitda_adjusted: Optional[float]


class BridgeLine(BaseModel):
    adjustment_id: str
    title: str
    category: str
    amount_cop: float
    status: str
    included: bool
    origin: str
    citation_id: str


class EbitdaBridge(BaseModel):
    period: str
    ebitda_reported_cop: float
    lines: List[BridgeLine]
    total_accepted_adjustments_cop: float
    total_pending_adjustments_cop: float
    total_rejected_adjustments_cop: float
    ebitda_adjusted_cop: float


class ValuationScenario(BaseModel):
    scenario: Literal["CONSERVADOR", "BASE", "OPTIMISTA"]
    percentile: Literal["P25", "MEDIANA", "P75"]
    ev_ebitda_multiple: float
    enterprise_value_cop: float
    net_financial_debt_cop: float
    equity_value_cop: float
    implied_ev_revenue: Optional[float]


class ValuationResult(BaseModel):
    status: Literal["OK", "MISSING_DATA", "NOT_MEANINGFUL"]
    valuation_period: str
    ciiu_code: str
    sector_key: Optional[str]
    sector_label: Optional[str]
    benchmark_status: Optional[str]
    ebitda_basis_cop: Optional[float]
    scenarios: List[ValuationScenario]
    sector_operating_benchmarks: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    message: Optional[str] = None


class ContingencyExposure(BaseModel):
    total_claimed_cop: float
    total_provisioned_cop: float
    unprovisioned_probable_or_possible_cop: float
    unprovisioned_pct_of_adjusted_ebitda: Optional[float]
    unprovisioned_pct_of_base_equity_value: Optional[float]
    proceeding_ids: List[str]


class GrowthSummary(BaseModel):
    first_period: str
    last_period: str
    revenue_cagr_pct: Optional[float]
    ebitda_adjusted_cagr_pct: Optional[float]


class EngineWarning(BaseModel):
    code: Literal[
        "BALANCE_MISMATCH",
        "UNMAPPED_ACCOUNTS",
        "NON_POSITIVE_EBITDA",
        "MISSING_BENCHMARK",
        "MISSING_PERIOD_DATA",
        "DIVISION_BY_ZERO",
    ]
    period: Optional[str] = None
    message: str


class FinancialEngineResult(BaseModel):
    engine_version: str
    llm_calls: int = Field(0, description="Siempre 0: el motor es 100 % determinista.")
    periods: List[str]
    income_statement: List[IncomeStatementMetrics]
    balance_sheet: List[BalanceSheetMetrics]
    working_capital: List[WorkingCapitalMetrics]
    leverage: List[LeverageMetrics]
    ebitda_bridge: List[EbitdaBridge]
    growth: GrowthSummary
    valuation: ValuationResult
    contingencies: ContingencyExposure
    unmapped_account_count: int
    warnings: List[EngineWarning]
    computation_ms: float
