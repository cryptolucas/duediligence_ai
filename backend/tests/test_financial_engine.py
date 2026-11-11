"""Tests del motor financiero determinista.

Verifican: (1) que ningún cálculo dependa de un LLM, (2) cifras exactas del caso demo,
(3) que los toggles de EbitdaAdjustment recalculen exactamente EBITDA ajustado, apalancamiento y
valoración, (4) validación de la ecuación contable y (5) manejo explícito de casos no calculables.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.schemas.deal import EbitdaAdjustment, LegalProceeding, MappedAccountItem, SourceCitation
from app.services import financial_engine as fe
from app.services.data_loader import load_benchmarks, load_demo_dossier

BACKEND_DIR = Path(__file__).resolve().parents[1]
M = 1_000_000.0  # COP millones

# ---------------------------------------------------------------------------
# Fixtures y fábricas
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def benchmarks() -> dict:
    return load_benchmarks()


@pytest.fixture()
def dossier():
    return load_demo_dossier()


@pytest.fixture()
def demo(dossier, benchmarks):
    _, result = fe.recalculate_dossier(dossier, benchmarks)
    return result


def row(rows, period):
    return next(r for r in rows if r.period == period)


def citation(cid: str = "cit_test") -> SourceCitation:
    return SourceCitation(
        citation_id=cid,
        document_id="doc_test",
        document_name="test.xlsx",
        page_or_sheet="Hoja1",
        cell_or_line_ref="C1",
        exact_quote="valor",
        confidence=1.0,
    )


def account(category: str, value: float, period: str = "2025", code: str | None = None) -> MappedAccountItem:
    return MappedAccountItem(
        raw_account_code=code,
        raw_account_name=f"{category} test",
        standard_category=category,
        period=period,
        raw_value_cop=value,
        mapping_rationale="test",
        citation=citation(f"cit_{category}_{period}_{value}"),
    )


def adjustment(adj_id: str, amount: float, period: str = "2025", status: str = "ACCEPTED") -> EbitdaAdjustment:
    return EbitdaAdjustment(
        id=adj_id,
        title=adj_id,
        category="OTHER",
        period=period,
        amount_cop=amount,
        rationale="test",
        status=status,
        citation=citation(f"cit_{adj_id}"),
    )


def balanced_company(period: str = "2025") -> list[MappedAccountItem]:
    """Empresa mínima: ingresos 1.000, costo 600, gastos 200, D&A 50, intereses 30, impuestos 40.

    Balance: caja 100 + CxC 150 + inventario 120 + PPE 630 = 1.000 = CxP 80 + deuda CP 120 + deuda LP 300 + patrimonio 500.
    """
    return [
        account("REVENUE", 1000.0, period),
        account("COGS", 600.0, period),
        account("SGA", 200.0, period),
        account("DA", 50.0, period),
        account("NET_INTEREST", 30.0, period),
        account("TAXES", 40.0, period),
        account("CASH", 100.0, period),
        account("ACCOUNTS_RECEIVABLE", 150.0, period),
        account("INVENTORY", 120.0, period),
        account("PPE_AND_INTANGIBLES", 630.0, period),
        account("ACCOUNTS_PAYABLE", 80.0, period),
        account("SHORT_TERM_DEBT", 120.0, period),
        account("LONG_TERM_DEBT", 300.0, period),
        account("EQUITY", 500.0, period),
    ]


# ---------------------------------------------------------------------------
# 1. Cero LLM en el motor
# ---------------------------------------------------------------------------

FORBIDDEN_MODULE_PREFIXES = ("litellm", "openai", "anthropic", "langgraph", "langchain", "google", "ollama", "httpx", "requests")
ALLOWED_IMPORT_ROOTS = {"__future__", "math", "time", "collections", "typing", "re", "app"}


@pytest.mark.parametrize("relative_path", ["app/services/financial_engine.py", "app/services/memo_renderer.py"])
def test_deterministic_modules_only_import_stdlib_and_schemas(relative_path):
    tree = ast.parse((BACKEND_DIR / relative_path).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for module in imported:
        assert module.split(".")[0] in ALLOWED_IMPORT_ROOTS, f"{relative_path} importa {module}"
        if module.startswith("app."):
            assert module.startswith("app.schemas"), f"{relative_path} solo puede depender de app.schemas, no de {module}"


def test_engine_runtime_loads_no_llm_client():
    code = (
        "import sys\n"
        "from app.services.financial_engine import recalculate_dossier\n"
        "from app.services.memo_renderer import render_memo\n"
        "from app.services.data_loader import load_demo_dossier, load_benchmarks\n"
        "d = load_demo_dossier()\n"
        "_, r = recalculate_dossier(d, load_benchmarks())\n"
        "render_memo(d.memo_markdown_template, r)\n"
        f"bad = [m for m in sys.modules if m.split('.')[0] in {FORBIDDEN_MODULE_PREFIXES!r}]\n"
        "print('BAD=' + ','.join(sorted(bad)))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, check=True)
    assert out.stdout.strip().endswith("BAD="), out.stdout


def test_result_reports_zero_llm_calls(demo):
    assert demo.llm_calls == 0


# ---------------------------------------------------------------------------
# 2. Cifras exactas del caso demo (COP)
# ---------------------------------------------------------------------------


def test_demo_income_statement_2025(demo):
    inc = row(demo.income_statement, "2025")
    assert inc.revenue.value_cop == 28_150 * M
    assert inc.cogs.value_cop == 18_860 * M
    assert inc.gross_profit_cop == 9_290 * M
    assert inc.sga.value_cop == 6_580 * M
    assert inc.other_operating_income_expense.value_cop == 15 * M
    assert inc.ebitda_reported_cop == 2_725 * M
    assert inc.depreciation_amortization.value_cop == 772 * M
    assert inc.net_interest.value_cop == 744 * M
    assert inc.net_income_cop == 786 * M
    assert inc.gross_margin_pct == pytest.approx(9_290 / 28_150 * 100)
    assert inc.ebitda_reported_margin_pct == pytest.approx(2_725 / 28_150 * 100)
    assert inc.revenue_growth_yoy_pct == pytest.approx((28_150 / 25_395 - 1) * 100)


def test_demo_net_income_reconciles_with_audited_equity_line(dossier, demo):
    """La utilidad neta calculada desde el balance de prueba debe igualar el 3605 citado del ESF dictaminado."""
    for inc in demo.income_statement:
        audited = next(a for a in dossier.mapped_accounts if a.raw_account_code == "3605" and a.period == inc.period)
        assert inc.net_income_cop == audited.raw_value_cop


def test_demo_adjusted_ebitda_by_period(demo):
    expected = {"2023": 2_785 * M, "2024": 3_131 * M, "2025": 3_447 * M}
    for period, value in expected.items():
        assert row(demo.income_statement, period).ebitda_adjusted_cop == value
        assert row(demo.ebitda_bridge, period).ebitda_adjusted_cop == value


def test_demo_bridge_excludes_pending_and_reports_it_separately(demo):
    bridge = row(demo.ebitda_bridge, "2025")
    assert bridge.total_accepted_adjustments_cop == (312 + 168 + 280 - 38) * M
    assert bridge.total_pending_adjustments_cop == 74 * M
    assert bridge.total_rejected_adjustments_cop == 0
    pending = [line for line in bridge.lines if line.status == "PENDING_REVIEW"]
    assert [line.adjustment_id for line in pending] == ["adj_2025_personal"]
    assert not pending[0].included


def test_demo_balance_sheet_ties_every_period(demo):
    for bal in demo.balance_sheet:
        assert bal.balance_check.is_balanced, bal.balance_check
        assert bal.balance_check.difference_cop == 0.0
    bal25 = row(demo.balance_sheet, "2025")
    assert bal25.total_assets_cop == 17_505 * M
    assert bal25.total_liabilities_cop == 11_568 * M
    assert bal25.equity.value_cop == 5_937 * M


def test_demo_working_capital_2025(demo):
    wc = row(demo.working_capital, "2025")
    assert wc.net_working_capital_cop == (4_770 + 4_000 - 2_760) * M
    assert wc.dso_days == pytest.approx(4_770 / 28_150 * 365)
    assert wc.dio_days == pytest.approx(4_000 / 18_860 * 365)
    assert wc.dpo_days == pytest.approx(2_760 / 18_860 * 365)
    assert wc.cash_conversion_cycle_days == pytest.approx(wc.dso_days + wc.dio_days - wc.dpo_days)


def test_demo_leverage_2025(demo):
    lev = row(demo.leverage, "2025")
    assert lev.gross_financial_debt_cop == (2_150 + 3_400 + 1_100 + 600) * M
    assert lev.net_financial_debt_cop == 6_705 * M
    assert lev.net_debt_to_ebitda_adjusted == pytest.approx(6_705 / 3_447)
    assert lev.net_debt_to_ebitda_reported == pytest.approx(6_705 / 2_725)


def test_demo_valuation_uses_sector_multiples(demo, benchmarks):
    val = demo.valuation
    assert val.status == "OK"
    assert val.sector_key == "MANUFACTURA_ALIMENTOS"
    assert val.valuation_period == "2025"
    multiples = benchmarks["sectors"]["MANUFACTURA_ALIMENTOS"]["ev_ebitda"]
    by_scenario = {s.scenario: s for s in val.scenarios}
    for scenario, key in (("CONSERVADOR", "p25"), ("BASE", "median"), ("OPTIMISTA", "p75")):
        s = by_scenario[scenario]
        assert s.ev_ebitda_multiple == multiples[key]
        assert s.enterprise_value_cop == pytest.approx(multiples[key] * 3_447 * M)
        assert s.equity_value_cop == pytest.approx(multiples[key] * 3_447 * M - 6_705 * M)
    assert by_scenario["CONSERVADOR"].equity_value_cop < by_scenario["BASE"].equity_value_cop < by_scenario["OPTIMISTA"].equity_value_cop


def test_demo_growth_and_contingencies(demo):
    assert demo.growth.revenue_cagr_pct == pytest.approx(((28_150 / 22_898) ** 0.5 - 1) * 100)
    assert demo.growth.ebitda_adjusted_cagr_pct == pytest.approx(((3_447 / 2_785) ** 0.5 - 1) * 100)
    c = demo.contingencies
    assert c.unprovisioned_probable_or_possible_cop == (850 + 310) * M
    assert c.unprovisioned_pct_of_adjusted_ebitda == pytest.approx(1_160 / 3_447 * 100)


def test_demo_unmapped_accounts_are_excluded_and_warned(demo):
    assert demo.unmapped_account_count == 2
    codes = [w.code for w in demo.warnings]
    assert codes == ["UNMAPPED_ACCOUNTS"]
    # 2023 cuadra sin las valorizaciones (1910/3805) porque se excluyen de ambos lados
    assert row(demo.balance_sheet, "2023").balance_check.is_balanced


def test_traced_values_point_to_existing_citations(dossier, demo):
    index = dossier.citation_index()
    for inc in demo.income_statement:
        for traced in (inc.revenue, inc.cogs, inc.sga, inc.depreciation_amortization, inc.net_interest, inc.taxes):
            assert traced.source_citation_ids, f"{inc.period}: cifra sin citas"
            assert all(cid in index for cid in traced.source_citation_ids)
    assert row(demo.income_statement, "2025").revenue.source_citation_ids == ["cit_bp25_4120", "cit_bp25_4175"]
    for bridge in demo.ebitda_bridge:
        assert all(line.citation_id in index for line in bridge.lines)


# ---------------------------------------------------------------------------
# 3. Sandbox: los toggles recalculan exactamente
# ---------------------------------------------------------------------------


def test_rejecting_adjustment_recalculates_ebitda_leverage_and_valuation(dossier, benchmarks):
    adjusted, result = fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_legal": "REJECTED"})
    new_ebitda = (3_447 - 280) * M
    inc = row(result.income_statement, "2025")
    assert inc.ebitda_adjusted_cop == new_ebitda
    assert inc.ebitda_adjusted_margin_pct == pytest.approx(new_ebitda / (28_150 * M) * 100)
    assert row(result.leverage, "2025").net_debt_to_ebitda_adjusted == pytest.approx(6_705 / 3_167)
    base = next(s for s in result.valuation.scenarios if s.scenario == "BASE")
    assert base.enterprise_value_cop == pytest.approx(6.0 * new_ebitda)
    assert base.equity_value_cop == pytest.approx(6.0 * new_ebitda - 6_705 * M)
    assert result.contingencies.unprovisioned_pct_of_adjusted_ebitda == pytest.approx(1_160 / 3_167 * 100)
    bridge = row(result.ebitda_bridge, "2025")
    assert bridge.total_rejected_adjustments_cop == 280 * M
    # Otros periodos y el EBITDA reportado no cambian
    assert inc.ebitda_reported_cop == 2_725 * M
    assert row(result.income_statement, "2024").ebitda_adjusted_cop == 3_131 * M
    assert next(a for a in adjusted if a.id == "adj_2025_legal").status == "REJECTED"


def test_accepting_pending_adjustment_adds_it(dossier, benchmarks):
    _, result = fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_personal": "ACCEPTED"})
    assert row(result.income_statement, "2025").ebitda_adjusted_cop == (3_447 + 74) * M
    assert row(result.ebitda_bridge, "2025").total_pending_adjustments_cop == 0


def test_rejecting_negative_adjustment_increases_ebitda(dossier, benchmarks):
    _, result = fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_gain_ppe": "REJECTED"})
    assert row(result.income_statement, "2025").ebitda_adjusted_cop == (3_447 + 38) * M


def test_rejecting_all_adjustments_returns_reported_ebitda(dossier, benchmarks):
    overrides = {a.id: "REJECTED" for a in dossier.ebitda_adjustments}
    _, result = fe.recalculate_dossier(dossier, benchmarks, overrides)
    for inc in result.income_statement:
        assert inc.ebitda_adjusted_cop == inc.ebitda_reported_cop
    lev = row(result.leverage, "2025")
    assert lev.net_debt_to_ebitda_adjusted == lev.net_debt_to_ebitda_reported


def test_toggle_round_trip_restores_original_result(dossier, benchmarks):
    _, original = fe.recalculate_dossier(dossier, benchmarks)
    _, toggled_back = fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_rent": "ACCEPTED"})
    assert original.model_dump(exclude={"computation_ms"}) == toggled_back.model_dump(exclude={"computation_ms"})


def test_manual_adjustment_is_included_and_marked(dossier, benchmarks):
    manual = adjustment("manual_bonus", -100 * M)
    adjusted, result = fe.recalculate_dossier(dossier, benchmarks, manual_adjustments=[manual])
    assert row(result.income_statement, "2025").ebitda_adjusted_cop == (3_447 - 100) * M
    assert next(a for a in adjusted if a.id == "manual_bonus").origin == "ANALYST_MANUAL"
    line = next(line for line in row(result.ebitda_bridge, "2025").lines if line.adjustment_id == "manual_bonus")
    assert line.included and line.origin == "ANALYST_MANUAL"


def test_manual_adjustment_can_be_toggled_by_override(dossier, benchmarks):
    manual = adjustment("manual_bonus", -100 * M)
    _, result = fe.recalculate_dossier(dossier, benchmarks, {"manual_bonus": "REJECTED"}, [manual])
    assert row(result.income_statement, "2025").ebitda_adjusted_cop == 3_447 * M


def test_overrides_do_not_mutate_source_dossier(dossier, benchmarks):
    before = [a.status for a in dossier.ebitda_adjustments]
    fe.recalculate_dossier(dossier, benchmarks, {a.id: "REJECTED" for a in dossier.ebitda_adjustments})
    assert [a.status for a in dossier.ebitda_adjustments] == before


@pytest.mark.parametrize(
    "overrides, manual, message",
    [
        ({"no_existe": "ACCEPTED"}, None, "inexistentes"),
        ({"adj_2025_legal": "MAYBE"}, None, "inválido"),
        (None, [adjustment("adj_2025_legal", 1.0)], "repite"),
    ],
)
def test_invalid_overrides_raise(dossier, benchmarks, overrides, manual, message):
    with pytest.raises(ValueError, match=message):
        fe.recalculate_dossier(dossier, benchmarks, overrides, manual)


def test_adjustment_for_unknown_period_raises(benchmarks):
    with pytest.raises(ValueError, match="periodos"):
        fe.run_financial_engine(balanced_company(), [adjustment("x", 1.0, period="2019")], "1020", benchmarks)


def test_recalculation_is_deterministic(dossier, benchmarks):
    _, a = fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_legal": "REJECTED"})
    _, b = fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_legal": "REJECTED"})
    assert a.model_dump(exclude={"computation_ms"}) == b.model_dump(exclude={"computation_ms"})


def test_recalculation_is_under_100ms(dossier, benchmarks):
    fe.recalculate_dossier(dossier, benchmarks)  # calentamiento
    runs = 25
    started = time.perf_counter()
    for i in range(runs):
        status = "REJECTED" if i % 2 else "ACCEPTED"
        fe.recalculate_dossier(dossier, benchmarks, {"adj_2025_legal": status})
    avg_ms = (time.perf_counter() - started) * 1000 / runs
    assert avg_ms < 100, f"Recálculo promedio {avg_ms:.2f} ms"


# ---------------------------------------------------------------------------
# 4. Ecuación contable
# ---------------------------------------------------------------------------


def test_balanced_company_passes_check(benchmarks):
    result = fe.run_financial_engine(balanced_company(), [], "1020", benchmarks)
    bal = result.balance_sheet[0]
    assert bal.total_assets_cop == 1000.0
    assert bal.total_liabilities_cop == 500.0
    assert bal.balance_check.is_balanced
    assert not [w for w in result.warnings if w.code == "BALANCE_MISMATCH"]


def test_balance_mismatch_emits_warning(benchmarks):
    accounts = balanced_company() + [account("CASH", 25_000.0)]
    result = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    check = result.balance_sheet[0].balance_check
    assert not check.is_balanced
    assert check.difference_cop == 25_000.0
    mismatch = [w for w in result.warnings if w.code == "BALANCE_MISMATCH"]
    assert len(mismatch) == 1 and mismatch[0].period == "2025"


def test_balance_tolerance_is_configurable(benchmarks):
    accounts = balanced_company() + [account("CASH", 500.0)]
    assert fe.run_financial_engine(accounts, [], "1020", benchmarks).balance_sheet[0].balance_check.is_balanced
    strict = fe.run_financial_engine(accounts, [], "1020", benchmarks, balance_tolerance_cop=1.0)
    assert not strict.balance_sheet[0].balance_check.is_balanced


def test_pre_closing_trial_balance_adds_current_result_to_equity(benchmarks):
    # Balance de prueba pre-cierre: el patrimonio no incluye la utilidad del año (80)
    accounts = [a for a in balanced_company() if a.standard_category != "EQUITY"] + [account("EQUITY", 420.0)]
    plain = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    assert plain.balance_sheet[0].balance_check.difference_cop == 80.0
    pre = fe.run_financial_engine(accounts, [], "1020", benchmarks, pre_closing_periods=["2025"])
    check = pre.balance_sheet[0].balance_check
    assert check.is_balanced and check.current_year_result_included_cop == 80.0
    assert check.total_equity_cop == 500.0


def test_contra_accounts_reduce_their_category(benchmarks):
    accounts = balanced_company() + [account("ACCOUNTS_RECEIVABLE", -50.0), account("EQUITY", -50.0)]
    result = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    assert result.balance_sheet[0].accounts_receivable.value_cop == 100.0
    assert result.balance_sheet[0].balance_check.is_balanced


def test_unmapped_items_never_enter_totals(benchmarks):
    accounts = balanced_company() + [account("UNMAPPED", 9_999_999.0)]
    result = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    assert result.income_statement[0].revenue.value_cop == 1000.0
    assert result.balance_sheet[0].balance_check.is_balanced
    assert result.unmapped_account_count == 1


# ---------------------------------------------------------------------------
# 5. Fórmulas y casos no calculables
# ---------------------------------------------------------------------------


def test_minimal_company_formulas(benchmarks):
    result = fe.run_financial_engine(balanced_company(), [adjustment("a1", 50.0)], "1020", benchmarks)
    inc = result.income_statement[0]
    assert inc.gross_profit_cop == 400.0
    assert inc.ebitda_reported_cop == 200.0
    assert inc.ebit_cop == 150.0
    assert inc.pre_tax_income_cop == 120.0
    assert inc.net_income_cop == 80.0
    assert inc.ebitda_adjusted_cop == 250.0
    assert inc.ebitda_adjusted_margin_pct == pytest.approx(25.0)
    assert inc.revenue_growth_yoy_pct is None  # primer periodo
    lev = result.leverage[0]
    assert lev.net_financial_debt_cop == 320.0
    assert lev.net_debt_to_ebitda_adjusted == pytest.approx(320.0 / 250.0)
    assert lev.interest_coverage_ebitda_adjusted == pytest.approx(250.0 / 30.0)
    wc = result.working_capital[0]
    assert wc.net_working_capital_cop == 190.0
    assert wc.current_ratio == pytest.approx(370.0 / 200.0)


def test_multi_period_growth(benchmarks):
    accounts = balanced_company("2024") + balanced_company("2025") + [account("REVENUE", 210.0, "2025")]
    result = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    assert row(result.income_statement, "2025").revenue_growth_yoy_pct == pytest.approx(21.0)
    assert result.growth.revenue_cagr_pct == pytest.approx(21.0)


def test_zero_revenue_yields_none_margins(benchmarks):
    accounts = [a for a in balanced_company() if a.standard_category != "REVENUE"]
    result = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    inc = result.income_statement[0]
    assert inc.gross_margin_pct is None
    assert inc.ebitda_reported_margin_pct is None
    assert result.working_capital[0].dso_days is None
    assert {"MISSING_PERIOD_DATA", "NON_POSITIVE_EBITDA"} <= {w.code for w in result.warnings}


def test_negative_ebitda_makes_leverage_and_valuation_not_meaningful(benchmarks):
    accounts = balanced_company() + [account("SGA", 500.0)]
    result = fe.run_financial_engine(accounts, [], "1020", benchmarks)
    assert result.income_statement[0].ebitda_adjusted_cop == -300.0
    assert result.leverage[0].net_debt_to_ebitda_adjusted is None
    assert result.valuation.status == "NOT_MEANINGFUL"
    assert result.valuation.scenarios == []
    assert result.contingencies.unprovisioned_pct_of_adjusted_ebitda is None


def test_missing_benchmark_marks_valuation_missing_data(benchmarks):
    result = fe.run_financial_engine(balanced_company(), [], "9999", benchmarks)
    assert result.valuation.status == "MISSING_DATA"
    assert "MISSING_BENCHMARK" in {w.code for w in result.warnings}


def test_ciiu_division_fallback(benchmarks):
    key, sector = fe.resolve_sector(benchmarks, "1089")
    assert key == "MANUFACTURA_ALIMENTOS"
    key, _ = fe.resolve_sector(benchmarks, "4699")  # no está en el catálogo, sí en la división 46
    assert key == "COMERCIO_MAYORISTA"
    assert fe.resolve_sector(benchmarks, "") == (None, None)


def test_contingency_exposure_rules():
    procs = [
        LegalProceeding(id="p1", proceeding_type="LABORAL", description="x", claimed_amount_cop=100.0,
                        provisioned_amount_cop=30.0, probability="PROBABLE", citation=citation("c1")),
        LegalProceeding(id="p2", proceeding_type="CIVIL_COMERCIAL", description="x", claimed_amount_cop=500.0,
                        probability="REMOTA", citation=citation("c2")),
        LegalProceeding(id="p3", proceeding_type="TRIBUTARIO", description="x", claimed_amount_cop=None,
                        probability="POSIBLE", citation=citation("c3")),
        LegalProceeding(id="p4", proceeding_type="LABORAL", description="x", claimed_amount_cop=10.0,
                        provisioned_amount_cop=20.0, probability="POSIBLE", citation=citation("c4")),
    ]
    exposure = fe.compute_contingency_exposure(procs, ebitda_adjusted=140.0, base_equity_value=700.0)
    assert exposure.total_claimed_cop == 610.0
    assert exposure.total_provisioned_cop == 50.0
    assert exposure.unprovisioned_probable_or_possible_cop == 70.0  # p1: 70, p4 sobre-provisionado: 0, p2 remota, p3 sin cuantía
    assert exposure.unprovisioned_pct_of_adjusted_ebitda == pytest.approx(50.0)
    assert exposure.unprovisioned_pct_of_base_equity_value == pytest.approx(10.0)


@pytest.mark.parametrize(
    "fn, args, expected",
    [
        (fe.safe_div, (1.0, 0.0), None),
        (fe.safe_div, (None, 2.0), None),
        (fe.pct, (25.0, 200.0), 12.5),
        (fe.growth_pct, (110.0, 100.0), pytest.approx(10.0)),
        (fe.growth_pct, (110.0, 0.0), None),
        (fe.growth_pct, (110.0, -5.0), None),
        (fe.cagr_pct, (100.0, 121.0, 2), pytest.approx(10.0)),
        (fe.cagr_pct, (100.0, 121.0, 0), None),
        (fe.cagr_pct, (-100.0, 121.0, 2), None),
        (fe.days_metric, (50.0, 365.0), pytest.approx(50.0)),
        (fe.days_metric, (50.0, 0.0), None),
        (fe.leverage_ratio, (300.0, 0.0), None),
        (fe.leverage_ratio, (300.0, 150.0), 2.0),
    ],
)
def test_arithmetic_primitives(fn, args, expected):
    assert fn(*args) == expected


def test_convert_cop():
    assert fe.convert_cop(28_150 * M, "COP_MILLONES") == 28_150.0
    assert fe.convert_cop(4_000_000.0, "USD", 4_000.0) == 1_000.0
    assert fe.convert_cop(None, "USD", 4_000.0) is None
    with pytest.raises(ValueError):
        fe.convert_cop(1.0, "USD")
    with pytest.raises(ValueError):
        fe.convert_cop(1.0, "EUR")
