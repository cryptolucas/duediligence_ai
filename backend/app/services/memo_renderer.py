"""Renderizador determinista del Memo de Comité.

El agente redactor escribe la narrativa con marcadores; nunca escribe cifras calculadas.
Este módulo reemplaza cada marcador con la salida del motor financiero, de modo que al
activar/desactivar un ajuste de EBITDA el memo se actualiza sin volver a llamar al LLM.

Marcadores soportados:
    {{metric:<nombre>:<periodo>}}            ej. {{metric:ebitda_adjusted:2025}}
    {{growth:<revenue_cagr_pct|ebitda_adjusted_cagr_pct>}}
    {{valuation:<ESCENARIO>:<multiple|enterprise_value|net_debt|equity_value|implied_ev_revenue>}}
    {{valuation:sector_label}}
    {{bridge:<periodo>:<total_accepted|total_pending|total_rejected>}}
    {{contingencies:<unprovisioned|total_claimed|pct_adj_ebitda|pct_base_equity>}}
    {{benchmark:<métrica>:<p25|median|p75>}}
Las citas [[cite:<citation_id>]] se conservan intactas para que el frontend las convierta en badges.
Un marcador que no se puede resolver se reemplaza por ⟦MISSING_DATA: ...⟧, nunca por un número inventado.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from app.schemas.financials import FinancialEngineResult

PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z_]+(?::[A-Za-z0-9_]+)*)\}\}")
CITATION_RE = re.compile(r"\[\[cite:([A-Za-z0-9_\-]+)\]\]")


# ---------------------------------------------------------------------------
# Formato colombiano
# ---------------------------------------------------------------------------


def _group_thousands(number: float, decimals: int) -> str:
    text = f"{abs(number):,.{decimals}f}"
    text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"-{text}" if number < 0 else text


def format_cop_millions(value_cop: Optional[float]) -> Optional[str]:
    if value_cop is None:
        return None
    return f"COP {_group_thousands(value_cop / 1_000_000.0, 0)} M"


def format_pct(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{_group_thousands(value, 1)} %"


def format_multiple(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{_group_thousands(value, 2)}x"


def format_days(value: Optional[float]) -> Optional[str]:
    return None if value is None else f"{_group_thousands(value, 0)} días"


# ---------------------------------------------------------------------------
# Resolución de marcadores
# ---------------------------------------------------------------------------


def _metric_resolvers(result: FinancialEngineResult) -> dict[str, Callable[[str], Optional[str]]]:
    inc = {row.period: row for row in result.income_statement}
    bal = {row.period: row for row in result.balance_sheet}
    wc = {row.period: row for row in result.working_capital}
    lev = {row.period: row for row in result.leverage}

    def by(table, fn, fmt):
        return lambda p: fmt(fn(table[p])) if p in table else None

    return {
        "revenue": by(inc, lambda r: r.revenue.value_cop, format_cop_millions),
        "revenue_growth_yoy_pct": by(inc, lambda r: r.revenue_growth_yoy_pct, format_pct),
        "gross_profit": by(inc, lambda r: r.gross_profit_cop, format_cop_millions),
        "gross_margin_pct": by(inc, lambda r: r.gross_margin_pct, format_pct),
        "ebitda_reported": by(inc, lambda r: r.ebitda_reported_cop, format_cop_millions),
        "ebitda_reported_margin_pct": by(inc, lambda r: r.ebitda_reported_margin_pct, format_pct),
        "ebitda_adjusted": by(inc, lambda r: r.ebitda_adjusted_cop, format_cop_millions),
        "ebitda_adjusted_margin_pct": by(inc, lambda r: r.ebitda_adjusted_margin_pct, format_pct),
        "net_income": by(inc, lambda r: r.net_income_cop, format_cop_millions),
        "net_margin_pct": by(inc, lambda r: r.net_margin_pct, format_pct),
        "cash": by(bal, lambda r: r.cash.value_cop, format_cop_millions),
        "total_assets": by(bal, lambda r: r.total_assets_cop, format_cop_millions),
        "nwc": by(wc, lambda r: r.net_working_capital_cop, format_cop_millions),
        "dso_days": by(wc, lambda r: r.dso_days, format_days),
        "dio_days": by(wc, lambda r: r.dio_days, format_days),
        "dpo_days": by(wc, lambda r: r.dpo_days, format_days),
        "gross_debt": by(lev, lambda r: r.gross_financial_debt_cop, format_cop_millions),
        "net_debt": by(lev, lambda r: r.net_financial_debt_cop, format_cop_millions),
        "net_debt_to_ebitda_reported": by(lev, lambda r: r.net_debt_to_ebitda_reported, format_multiple),
        "net_debt_to_ebitda_adjusted": by(lev, lambda r: r.net_debt_to_ebitda_adjusted, format_multiple),
    }


def resolve_placeholder(token: str, result: FinancialEngineResult) -> Optional[str]:
    parts = token.split(":")
    kind, args = parts[0], parts[1:]

    if kind == "metric" and len(args) == 2:
        resolver = _metric_resolvers(result).get(args[0])
        return resolver(args[1]) if resolver else None

    if kind == "growth" and len(args) == 1:
        value = getattr(result.growth, args[0], None)
        return format_pct(value) if isinstance(value, (int, float)) else None

    if kind == "valuation":
        val = result.valuation
        if args == ["sector_label"]:
            return val.sector_label
        if len(args) == 2:
            scenario = next((s for s in val.scenarios if s.scenario == args[0]), None)
            if scenario is None:
                return None
            field_map = {
                "multiple": format_multiple(scenario.ev_ebitda_multiple),
                "enterprise_value": format_cop_millions(scenario.enterprise_value_cop),
                "net_debt": format_cop_millions(scenario.net_financial_debt_cop),
                "equity_value": format_cop_millions(scenario.equity_value_cop),
                "implied_ev_revenue": format_multiple(scenario.implied_ev_revenue),
            }
            return field_map.get(args[1])
        return None

    if kind == "bridge" and len(args) == 2:
        bridge = next((b for b in result.ebitda_bridge if b.period == args[0]), None)
        if bridge is None:
            return None
        field_map = {
            "total_accepted": bridge.total_accepted_adjustments_cop,
            "total_pending": bridge.total_pending_adjustments_cop,
            "total_rejected": bridge.total_rejected_adjustments_cop,
        }
        return format_cop_millions(field_map[args[1]]) if args[1] in field_map else None

    if kind == "contingencies" and len(args) == 1:
        c = result.contingencies
        field_map = {
            "unprovisioned": format_cop_millions(c.unprovisioned_probable_or_possible_cop),
            "total_claimed": format_cop_millions(c.total_claimed_cop),
            "pct_adj_ebitda": format_pct(c.unprovisioned_pct_of_adjusted_ebitda),
            "pct_base_equity": format_pct(c.unprovisioned_pct_of_base_equity_value),
        }
        return field_map.get(args[0])

    if kind == "benchmark" and len(args) == 2:
        stats = result.valuation.sector_operating_benchmarks.get(args[0])
        if not stats or args[1] not in stats:
            return None
        value = stats[args[1]]
        if args[0].endswith("_pct"):
            return format_pct(value)
        if args[0].endswith("_days"):
            return format_days(value)
        return format_multiple(value)

    return None


def render_memo(template: str, result: FinancialEngineResult) -> str:
    def _sub(match: re.Match) -> str:
        token = match.group(1)
        value = resolve_placeholder(token, result)
        return value if value is not None else f"⟦MISSING_DATA: {token}⟧"

    return PLACEHOLDER_RE.sub(_sub, template)


def extract_citation_ids(markdown: str) -> list[str]:
    return CITATION_RE.findall(markdown)


def extract_placeholders(markdown: str) -> list[str]:
    return PLACEHOLDER_RE.findall(markdown)
