"""Nodo 2 — Agente Financiero y Societario.

Con LLM: propone ajustes al EBITDA y extrae datos societarios/litigios. Cada propuesta pasa por el
guardián de citas; los montos se convierten a COP de forma determinista según las unidades del
documento y se verifica que la cifra aparezca literalmente en la cita.
Sin LLM: extrae datos del certificado de Cámara de Comercio con expresiones regulares (no inventa
ajustes ni litigios; quedan como información faltante).
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from app.agents.context import AgentRuntime, NodeTimer, documents_context, units_multiplier
from app.agents.llm_schemas import AnalystResponse, Evidence, ProposedFact
from app.agents.prompts import FINANCIAL_LEGAL_ANALYST
from app.schemas.deal import (
    CitedFact,
    CorporateProfile,
    EbitdaAdjustment,
    LegalProceeding,
    Shareholder,
    SourceCitation,
    SourceDocument,
)
from app.services.citation_guard import build_citation, verify_quote
from app.services.llm_client import LLMError
from app.services.numbers import amount_supported_by_text

AUTHORITATIVE_TYPES = {"CHAMBER_OF_COMMERCE_CERT", "FINANCIAL_STATEMENTS_PDF", "TRIAL_BALANCE_XLSX"}

FACT_LABELS = {
    "legal_name": "Razón social",
    "nit": "NIT",
    "ciiu_primary": "CIIU principal",
    "ciiu_secondary": "CIIU secundario",
    "domicile": "Domicilio",
    "incorporation": "Constitución",
    "legal_representative": "Representante legal",
    "alternate_legal_representative": "Suplente del representante legal",
}


def _doc_type(documents: Sequence[SourceDocument], document_id: str) -> str:
    return next((d.document_type for d in documents if d.document_id == document_id), "OTHER")


def _verify(documents: Sequence[SourceDocument], evidence: Evidence, confidence: float = 0.85) -> Optional[SourceCitation]:
    return verify_quote(documents, evidence.document_id, evidence.page_or_sheet, evidence.exact_quote, confidence).citation


def _fact_from_proposal(
    label: str, proposal: Optional[ProposedFact], documents: Sequence[SourceDocument], rejected: list[str]
) -> CitedFact:
    if proposal is None or not proposal.value.strip():
        return CitedFact(label=label, status="MISSING_DATA")
    citation = _verify(documents, proposal.evidence, 0.9)
    if citation is None:
        rejected.append(f"{label}: cita no encontrada en los documentos")
        return CitedFact(label=label, status="MISSING_DATA")
    status = "VERIFIED" if _doc_type(documents, citation.document_id) in AUTHORITATIVE_TYPES else "UNVERIFIED"
    return CitedFact(label=label, value=proposal.value.strip(), status=status, citation=citation)


def missing_profile() -> dict:
    return {key: CitedFact(label=label, status="MISSING_DATA") for key, label in FACT_LABELS.items()}


# ---------------------------------------------------------------------------
# Modo LLM
# ---------------------------------------------------------------------------


def analyze_with_llm(
    documents: Sequence[SourceDocument], periods: Sequence[str], runtime: AgentRuntime, notes: list[str]
) -> tuple[list[EbitdaAdjustment], CorporateProfile]:
    context = documents_context(documents)
    if not context:
        notes.append("No hay notas, certificados ni teaser para el agente financiero y societario.")
        return [], CorporateProfile(**missing_profile(), statutory_limits=[], shareholders=[], legal_proceedings=[])
    response = runtime.llm.complete_json(  # type: ignore[union-attr]
        FINANCIAL_LEGAL_ANALYST,
        f"Periodos analizados: {', '.join(periods)}\n\nDOCUMENTOS:\n{context}",
        AnalystResponse,
        deal_id=runtime.deal_id,
        task="analyst",
    )
    rejected: list[str] = []
    by_id = {d.document_id: d for d in documents}

    adjustments: list[EbitdaAdjustment] = []
    for n, prop in enumerate(response.adjustments, start=1):
        if prop.period not in periods:
            rejected.append(f"Ajuste '{prop.title}': periodo {prop.period} fuera del análisis")
            continue
        result = verify_quote(documents, prop.evidence.document_id, prop.evidence.page_or_sheet, prop.evidence.exact_quote, 0.85)
        if result.citation is None:
            rejected.append(f"Ajuste '{prop.title}': cita no encontrada literalmente")
            continue
        doc = by_id[result.citation.document_id]
        multiplier = units_multiplier(doc)
        amount_cop = abs(prop.amount_as_reported) * multiplier * (1 if prop.direction == "ADD_BACK" else -1)
        literal_ok = amount_supported_by_text(prop.amount_as_reported, result.citation.exact_quote, (1.0,))
        status = "ACCEPTED" if literal_ok and not result.relocated else "PENDING_REVIEW"
        rationale = prop.rationale
        if not literal_ok:
            rationale = f"⚠ La cifra propuesta no aparece literalmente en la cita; requiere revisión. {rationale}"
        rationale += f" (Monto convertido desde {doc.reported_units}.)"
        adjustments.append(
            EbitdaAdjustment(
                id=f"adj_{prop.period}_{n:02d}",
                title=prop.title,
                category=prop.category,
                period=prop.period,
                amount_cop=amount_cop,
                rationale=rationale,
                status=status,  # type: ignore[arg-type]
                citation=result.citation,
            )
        )

    facts = {key: _fact_from_proposal(label, getattr(response, key), documents, rejected) for key, label in FACT_LABELS.items()}
    limits = []
    for limit in response.statutory_limits:
        citation = _verify(documents, limit.evidence, 0.9)
        if citation is None:
            rejected.append(f"Límite estatutario '{limit.label}': cita no encontrada")
            continue
        limits.append(CitedFact(label=limit.label, value=limit.value, status="VERIFIED", citation=citation))

    shareholders = []
    for holder in response.shareholders:
        citation = _verify(documents, holder.evidence, 0.85)
        if citation is None:
            rejected.append(f"Accionista '{holder.name}': cita no encontrada")
            continue
        authoritative = _doc_type(documents, citation.document_id) in AUTHORITATIVE_TYPES
        shareholders.append(
            Shareholder(
                name=holder.name,
                ownership_pct=holder.ownership_pct,
                verification_status="VERIFIED" if authoritative else "UNVERIFIED",
                citation=citation,
            )
        )

    proceedings = []
    for n, proc in enumerate(response.legal_proceedings, start=1):
        result = verify_quote(documents, proc.evidence.document_id, proc.evidence.page_or_sheet, proc.evidence.exact_quote, 0.85)
        if result.citation is None:
            rejected.append(f"Proceso '{proc.description[:60]}': cita no encontrada")
            continue
        multiplier = units_multiplier(by_id[result.citation.document_id])
        claimed = proc.claimed_amount_as_reported
        if claimed is not None and not amount_supported_by_text(claimed, result.citation.exact_quote, (1.0,)):
            rejected.append(f"Proceso '{proc.description[:60]}': cuantía no literal en la cita; se deja sin cuantía")
            claimed = None
        proceedings.append(
            LegalProceeding(
                id=f"lit_{n:02d}_{proc.proceeding_type.lower()}",
                proceeding_type=proc.proceeding_type,
                description=proc.description,
                claimed_amount_cop=None if claimed is None else abs(claimed) * multiplier,
                provisioned_amount_cop=abs(proc.provisioned_amount_as_reported) * multiplier,
                probability=proc.probability,
                citation=result.citation,
            )
        )
    if rejected:
        notes.append("Propuestas descartadas o degradadas por el guardián de citas: " + "; ".join(rejected))
    profile = CorporateProfile(**facts, statutory_limits=limits, shareholders=shareholders, legal_proceedings=proceedings)
    return adjustments, profile


# ---------------------------------------------------------------------------
# Modo reglas (sin LLM)
# ---------------------------------------------------------------------------

_FACT_PATTERNS: dict[str, re.Pattern] = {
    "legal_name": re.compile(r"(?:raz[óo]n social|nombre)\s*:\s*(.+)", re.IGNORECASE),
    "nit": re.compile(r"\bNIT\b\.?\s*:?\s*(\d{3}\.?\d{3}\.?\d{3}\s*-\s*\d)", re.IGNORECASE),
    "domicile": re.compile(r"domicilio[^:\n]*:\s*(.+)", re.IGNORECASE),
    "incorporation": re.compile(r"constituci[óo]n\s*:\s*(.+)", re.IGNORECASE),
    "legal_representative": re.compile(r"^(?!.*suplente)(?:.*\b(?:gerente|representante legal)\b[^:\n]*):\s*(.+)", re.IGNORECASE),
    "alternate_legal_representative": re.compile(r"suplente[^:\n]*:\s*(.+)", re.IGNORECASE),
}
_CIIU = re.compile(r"CIIU\s*:?\s*(\d{4})\s*[-–]?\s*([^|\n]*)", re.IGNORECASE)
_LIMIT = re.compile(r"(requerir[áa] autorizaci[óo]n|le est[áa] prohibido|no podr[áa])", re.IGNORECASE)


def analyze_with_rules(documents: Sequence[SourceDocument], notes: list[str]) -> CorporateProfile:
    facts = missing_profile()
    limits: list[CitedFact] = []
    certs = [d for d in documents if d.document_type == "CHAMBER_OF_COMMERCE_CERT"]
    if not certs:
        notes.append("No se cargó certificado de Cámara de Comercio: datos societarios quedan como MISSING_DATA.")
    ciiu_found: list[tuple[str, SourceCitation]] = []
    for doc in certs:
        for page in doc.pages:
            for line in page.content.splitlines():
                for key, pattern in _FACT_PATTERNS.items():
                    if facts[key].status != "MISSING_DATA":
                        continue
                    match = pattern.search(line)
                    if match and match.group(1).strip():
                        facts[key] = CitedFact(
                            label=FACT_LABELS[key],
                            value=match.group(1).strip().title() if key.endswith("representative") else match.group(1).strip(),
                            status="VERIFIED",
                            citation=build_citation(doc, page.page_or_sheet, line, 0.8),
                        )
                ciiu = _CIIU.search(line)
                if ciiu:
                    ciiu_found.append((f"{ciiu.group(1)} - {ciiu.group(2).strip()}".strip(" -"), build_citation(doc, page.page_or_sheet, line, 0.85)))
                if _LIMIT.search(line):
                    limits.append(
                        CitedFact(
                            label=f"Restricción estatutaria {len(limits) + 1}",
                            value=line[:220],
                            status="VERIFIED",
                            citation=build_citation(doc, page.page_or_sheet, line, 0.8),
                        )
                    )
    for key, (value, citation) in zip(("ciiu_primary", "ciiu_secondary"), ciiu_found):
        facts[key] = CitedFact(label=FACT_LABELS[key], value=value, status="VERIFIED", citation=citation)
    notes.append("Modo reglas: ajustes de EBITDA, accionistas y litigios no se extraen automáticamente; el analista puede agregarlos.")
    return CorporateProfile(**facts, statutory_limits=limits, shareholders=[], legal_proceedings=[])


def resolve_company(profile: CorporateProfile, hints: dict, documents: Sequence[SourceDocument]) -> dict:
    """Identidad del deal: datos citados del certificado o, en su defecto, los que digitó el analista."""
    def value(fact: CitedFact, hint_key: str) -> str:
        if fact.value:
            return fact.value
        return (hints.get(hint_key) or "").strip() or "MISSING_DATA"

    ciiu_raw = value(profile.ciiu_primary, "ciiu_code")
    ciiu_match = re.match(r"\d{4}", ciiu_raw)
    domicile = profile.domicile.value or hints.get("city") or "MISSING_DATA"
    name = value(profile.legal_name, "company_name")
    if name == "MISSING_DATA" and documents:
        name = f"Empresa sin identificar ({documents[0].document_name})"
    return {
        "company_name": name,
        "nit": value(profile.nit, "nit"),
        "ciiu_code": ciiu_match.group(0) if ciiu_match else ciiu_raw,
        "city": domicile,
    }


def run_analyst(state: dict, runtime: AgentRuntime) -> dict:
    timer = NodeTimer("node_financial_and_legal_analyst", runtime.effective_mode)
    calls_before = getattr(runtime.llm, "calls", 0)
    notes: list[str] = []
    documents = state["documents"]
    adjustments: list[EbitdaAdjustment] = []
    profile: Optional[CorporateProfile] = None
    if runtime.uses_llm:
        try:
            adjustments, profile = analyze_with_llm(documents, state["periods"], runtime, notes)
        except LLMError as exc:
            notes.append(f"Fallo del LLM ({exc}); se usa extracción por reglas.")
    if profile is None:
        profile = analyze_with_rules(documents, notes)
    company = resolve_company(profile, state.get("company_hints", {}), documents)
    return {
        "ebitda_adjustments": adjustments,
        "corporate_profile": profile,
        "company": company,
        "processing_log": [
            timer.entry(
                f"{len(adjustments)} ajuste(s) de EBITDA propuestos; {len(profile.legal_proceedings)} proceso(s) legales; "
                f"{len(profile.shareholders)} accionista(s).",
                llm_calls=getattr(runtime.llm, "calls", 0) - calls_before,
                notes=notes,
            )
        ],
    }
