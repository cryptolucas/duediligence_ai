"""Salidas estructuradas (Pydantic) que cada agente LLM debe devolver.

Principio: el LLM clasifica, extrae texto literal y propone; nunca calcula. Por eso los montos se
piden "tal como aparecen en la cita" (``amount_as_reported``) y la conversión a COP la hace el
código según las unidades del documento.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.deal import AdjustmentCategory, RedFlagDomain, RedFlagSeverity, StandardCategory


class Evidence(BaseModel):
    document_id: str
    page_or_sheet: str
    exact_quote: str = Field(..., description="Fragmento copiado literalmente del documento (sin parafrasear).")


# --- Agente de Ingesta ------------------------------------------------------


class AccountClassification(BaseModel):
    row_id: str
    standard_category: StandardCategory
    rationale: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class AccountMappingResponse(BaseModel):
    items: List[AccountClassification]


class StatementLineClassification(BaseModel):
    line_id: str
    action: Literal["MAP", "SKIP"] = Field(..., description="SKIP para títulos, subtotales y totales.")
    standard_category: Optional[StandardCategory] = None
    nature: Optional[Literal["INCOME", "EXPENSE", "ASSET", "LIABILITY", "EQUITY", "CONTRA"]] = None
    period: Optional[str] = Field(None, description="Año de la columna elegida, ej. '2025'.")
    column_index: Optional[int] = Field(None, ge=0, description="Índice (0 = primer número) de la cifra dentro de la línea.")
    rationale: str = ""


class StatementMappingResponse(BaseModel):
    items: List[StatementLineClassification]


# --- Agente Financiero y Societario -----------------------------------------


class ProposedAdjustment(BaseModel):
    title: str
    category: AdjustmentCategory
    period: str
    direction: Literal["ADD_BACK", "DEDUCT"] = Field(..., description="ADD_BACK suma al EBITDA; DEDUCT resta.")
    amount_as_reported: float = Field(..., description="Cifra tal como aparece en la cita, sin convertir unidades.")
    rationale: str
    evidence: Evidence


class ProposedFact(BaseModel):
    value: str
    evidence: Evidence


class ProposedLimit(BaseModel):
    label: str
    value: str
    evidence: Evidence


class ProposedShareholder(BaseModel):
    name: str
    ownership_pct: Optional[float] = Field(None, ge=0, le=100)
    evidence: Evidence


class ProposedProceeding(BaseModel):
    proceeding_type: Literal["LABORAL", "TRIBUTARIO", "CIVIL_COMERCIAL", "ADMINISTRATIVO"]
    description: str
    claimed_amount_as_reported: Optional[float] = None
    provisioned_amount_as_reported: float = 0.0
    probability: Literal["PROBABLE", "POSIBLE", "REMOTA", "NO_INFORMADA"]
    evidence: Evidence


class AnalystResponse(BaseModel):
    adjustments: List[ProposedAdjustment] = Field(default_factory=list)
    legal_name: Optional[ProposedFact] = None
    nit: Optional[ProposedFact] = None
    ciiu_primary: Optional[ProposedFact] = None
    ciiu_secondary: Optional[ProposedFact] = None
    domicile: Optional[ProposedFact] = None
    incorporation: Optional[ProposedFact] = None
    legal_representative: Optional[ProposedFact] = None
    alternate_legal_representative: Optional[ProposedFact] = None
    statutory_limits: List[ProposedLimit] = Field(default_factory=list)
    shareholders: List[ProposedShareholder] = Field(default_factory=list)
    legal_proceedings: List[ProposedProceeding] = Field(default_factory=list)


# --- Agente Escéptico -------------------------------------------------------


class ProposedRedFlag(BaseModel):
    severity: RedFlagSeverity
    domain: RedFlagDomain
    title: str
    challenge_by_skeptic: str
    mitigation_question: str
    evidence: List[Evidence] = Field(..., min_length=1)


class ProposedMissingInfo(BaseModel):
    category: str
    requested_document_or_clarification: str
    why_it_matters_plain_spanish: str
    priority: Literal["MUST_HAVE_FOR_IC", "NICE_TO_HAVE"]


class SkepticResponse(BaseModel):
    red_flags: List[ProposedRedFlag] = Field(default_factory=list)
    missing_info: List[ProposedMissingInfo] = Field(default_factory=list)


# --- Redactor y chat --------------------------------------------------------


class MemoResponse(BaseModel):
    memo_markdown: str


class ChatLLMResponse(BaseModel):
    answer_markdown: str = Field(..., description="Respuesta con [[cite:id]] y marcadores {{...}} para cifras calculadas.")
    scenario_overrides: Dict[str, Literal["ACCEPTED", "REJECTED", "PENDING_REVIEW"]] = Field(
        default_factory=dict,
        description="Si la pregunta simula un escenario: estados de ajustes a probar (id -> estado).",
    )
