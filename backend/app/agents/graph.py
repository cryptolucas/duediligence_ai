"""Orquestador multiagente (LangGraph): 5 nodos secuenciales sobre ``DealDossierState``.

    node_ingestor_and_puc_mapper -> node_financial_and_legal_analyst -> node_deterministic_financial_engine
    -> node_skeptic_red_team -> node_ic_memo_writer

Aislamiento: cada operación se ejecuta con su propio estado y su propio ``AgentRuntime`` (cliente LLM,
modo y benchmarks) inyectado vía ``config["configurable"]``; el grafo compilado no guarda estado.

Modos:
* CLOUD_API / LOCAL_OLLAMA: agentes LLM + guardián de citas + motor determinista.
* RULES_FALLBACK: sin claves (o sin Ollama). Parser + reglas PUC + regex + reglas del escéptico + memo plantilla.
* SEED_FALLBACK: caso demo precargado; los nodos LLM devuelven la salida curada del seed y el motor
  determinista corre de verdad, así el MVP es 100 % probable desde el primer minuto.
"""

from __future__ import annotations

import operator
from functools import lru_cache
from typing import Annotated, Any, Mapping, Optional, Sequence, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.analyst import run_analyst
from app.agents.context import AgentRuntime, NodeTimer
from app.agents.ingestor import run_ingestor
from app.agents.memo_writer import run_memo_writer
from app.agents.skeptic import run_skeptic
from app.schemas.deal import (
    CorporateProfile,
    DealDossier,
    EbitdaAdjustment,
    MappedAccountItem,
    MissingInfoItem,
    RedFlagItem,
    SourceCitation,
    SourceDocument,
    UnreadableItem,
)
from app.schemas.financials import FinancialEngineResult
from app.services.document_parser import ParsedDocument
from app.services.financial_engine import run_financial_engine
from app.services.llm_client import StructuredLLM


class DealDossierState(TypedDict, total=False):
    deal_id: str
    effective_mode: str
    company_hints: dict
    parsed_documents: list[ParsedDocument]
    seed: Optional[DealDossier]
    # Nodo 1
    documents: list[SourceDocument]
    mapped_accounts: list[MappedAccountItem]
    unreadable_items: list[UnreadableItem]
    pre_closing_periods: list[str]
    periods: list[str]
    # Nodo 2
    ebitda_adjustments: list[EbitdaAdjustment]
    corporate_profile: CorporateProfile
    company: dict
    # Nodo 3
    financials: FinancialEngineResult
    # Nodo 4
    red_flags: list[RedFlagItem]
    missing_info: list[MissingInfoItem]
    # Nodo 5
    memo_template: str
    memo_citations: list[SourceCitation]
    # Bitácora acumulativa
    processing_log: Annotated[list[dict], operator.add]


def _runtime(config: RunnableConfig) -> AgentRuntime:
    return config["configurable"]["runtime"]


# ---------------------------------------------------------------------------
# Nodos
# ---------------------------------------------------------------------------


def node_ingestor_and_puc_mapper(state: DealDossierState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    seed = state.get("seed")
    if seed is not None:
        timer = NodeTimer("node_ingestor_and_puc_mapper", "SEED_FALLBACK")
        return {
            "documents": seed.documents,
            "mapped_accounts": seed.mapped_accounts,
            "unreadable_items": seed.unreadable_or_unmapped_items,
            "pre_closing_periods": seed.pre_closing_trial_balance_periods,
            "periods": seed.periods,
            "processing_log": [timer.entry(f"Caso demo: {len(seed.mapped_accounts)} cuentas precargadas con cita.")],
        }
    return run_ingestor(state["parsed_documents"], runtime)


def node_financial_and_legal_analyst(state: DealDossierState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    seed = state.get("seed")
    if seed is not None:
        timer = NodeTimer("node_financial_and_legal_analyst", "SEED_FALLBACK")
        return {
            "ebitda_adjustments": seed.ebitda_adjustments,
            "corporate_profile": seed.corporate_profile,
            "company": {"company_name": seed.company_name, "nit": seed.nit, "ciiu_code": seed.ciiu_code, "city": seed.city},
            "processing_log": [timer.entry(f"Caso demo: {len(seed.ebitda_adjustments)} ajustes y perfil societario precargados.")],
        }
    return run_analyst(dict(state), runtime)


def node_deterministic_financial_engine(state: DealDossierState, config: RunnableConfig) -> dict:
    """Motor 100 % Python: CERO LLM."""
    runtime = _runtime(config)
    timer = NodeTimer("node_deterministic_financial_engine", "DETERMINISTIC")
    result = run_financial_engine(
        accounts=state["mapped_accounts"],
        adjustments=state["ebitda_adjustments"],
        ciiu_code=state["company"]["ciiu_code"],
        benchmarks=runtime.benchmarks,
        legal_proceedings=state["corporate_profile"].legal_proceedings,
        periods=state["periods"],
        pre_closing_periods=state.get("pre_closing_periods", []),
    )
    balanced = sum(1 for b in result.balance_sheet if b.balance_check.is_balanced)
    return {
        "financials": result,
        "processing_log": [
            timer.entry(
                f"Motor determinista: {balanced}/{len(result.balance_sheet)} balances cuadran; valoración {result.valuation.status}; "
                f"{len(result.warnings)} advertencia(s).",
                llm_calls=0,
            )
        ],
    }


def node_skeptic_red_team(state: DealDossierState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    seed = state.get("seed")
    if seed is not None:
        timer = NodeTimer("node_skeptic_red_team", "SEED_FALLBACK")
        return {
            "red_flags": seed.red_flags,
            "missing_info": seed.missing_info,
            "processing_log": [timer.entry(f"Caso demo: {len(seed.red_flags)} red flags del escéptico precargadas.")],
        }
    return run_skeptic(dict(state), runtime)


def node_ic_memo_writer(state: DealDossierState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    seed = state.get("seed")
    if seed is not None:
        timer = NodeTimer("node_ic_memo_writer", "SEED_FALLBACK")
        return {
            "memo_template": seed.memo_markdown_template,
            "memo_citations": seed.memo_citations,
            "processing_log": [timer.entry("Caso demo: memo precargado; cifras resueltas por el motor.")],
        }
    citations = _collect_citations(state)
    return {**run_memo_writer(dict(state), runtime, citations), "memo_citations": []}


def _collect_citations(state: Mapping[str, Any]) -> list[SourceCitation]:
    found: list[SourceCitation] = [a.citation for a in state.get("mapped_accounts", [])]
    found += [a.citation for a in state.get("ebitda_adjustments", [])]
    for flag in state.get("red_flags", []):
        found += flag.citations
    found += [u.citation for u in state.get("unreadable_items", []) if u.citation is not None]
    profile: Optional[CorporateProfile] = state.get("corporate_profile")
    if profile is not None:
        facts = [
            profile.legal_name, profile.nit, profile.ciiu_primary, profile.ciiu_secondary, profile.domicile,
            profile.incorporation, profile.legal_representative, profile.alternate_legal_representative,
            *profile.statutory_limits,
        ]
        found += [f.citation for f in facts if f.citation is not None]
        found += [s.citation for s in profile.shareholders if s.citation is not None]
        found += [p.citation for p in profile.legal_proceedings]
    return found


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------

NODE_SEQUENCE = (
    ("node_ingestor_and_puc_mapper", node_ingestor_and_puc_mapper),
    ("node_financial_and_legal_analyst", node_financial_and_legal_analyst),
    ("node_deterministic_financial_engine", node_deterministic_financial_engine),
    ("node_skeptic_red_team", node_skeptic_red_team),
    ("node_ic_memo_writer", node_ic_memo_writer),
)


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(DealDossierState)
    for name, fn in NODE_SEQUENCE:
        graph.add_node(name, fn)
    graph.add_edge(START, NODE_SEQUENCE[0][0])
    for (a, _), (b, _) in zip(NODE_SEQUENCE, NODE_SEQUENCE[1:]):
        graph.add_edge(a, b)
    graph.add_edge(NODE_SEQUENCE[-1][0], END)
    return graph.compile()


def run_deal_pipeline(
    *,
    deal_id: str,
    effective_mode: str,
    benchmarks: Mapping[str, Any],
    llm: Optional[StructuredLLM] = None,
    parsed_documents: Sequence[ParsedDocument] = (),
    seed: Optional[DealDossier] = None,
    company_hints: Optional[dict] = None,
    created_at=None,
) -> tuple[DealDossier, FinancialEngineResult, list[dict]]:
    """Ejecuta el grafo completo para una operación y devuelve el expediente validado."""
    from datetime import datetime, timezone

    runtime = AgentRuntime(deal_id=deal_id, effective_mode=effective_mode, benchmarks=benchmarks, llm=llm)
    initial: DealDossierState = {
        "deal_id": deal_id,
        "effective_mode": effective_mode,
        "company_hints": company_hints or {},
        "parsed_documents": list(parsed_documents),
        "seed": seed,
        "processing_log": [],
    }
    final = build_graph().invoke(initial, config={"configurable": {"runtime": runtime}})
    company = final["company"]
    dossier = DealDossier(
        deal_id=deal_id,
        created_at=created_at or datetime.now(timezone.utc),
        llm_mode=effective_mode,  # type: ignore[arg-type]
        company_name=company["company_name"],
        nit=company["nit"],
        ciiu_code=company["ciiu_code"],
        city=company["city"],
        periods=final["periods"],
        pre_closing_trial_balance_periods=final.get("pre_closing_periods", []),
        documents=final["documents"],
        mapped_accounts=final["mapped_accounts"],
        unreadable_or_unmapped_items=final["unreadable_items"],
        ebitda_adjustments=final["ebitda_adjustments"],
        corporate_profile=final["corporate_profile"],
        red_flags=final["red_flags"],
        missing_info=final["missing_info"],
        memo_markdown_template=final["memo_template"],
        memo_citations=final.get("memo_citations", []),
    )
    return dossier, final["financials"], final["processing_log"]
