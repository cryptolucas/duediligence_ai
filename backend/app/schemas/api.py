"""Contratos de la API REST."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.deal import AdjustmentCategory, AdjustmentStatus, DealDossier, EbitdaAdjustment, RedFlagItem, SourceCitation
from app.schemas.financials import FinancialEngineResult


class DealSummary(BaseModel):
    deal_id: str
    company_name: str
    nit: str
    ciiu_code: str
    llm_mode: str
    requested_mode: str
    created_at: datetime
    updated_at: datetime
    periods: List[str]
    last_period: str
    revenue_last_cop: float
    ebitda_adjusted_last_cop: float
    all_balances_tie: bool
    red_flags_by_severity: Dict[str, int]


class DealView(BaseModel):
    dossier: DealDossier
    financials: FinancialEngineResult
    memo_markdown: str = Field(..., description="Memo con cifras ya resueltas por el motor; conserva [[cite:id]].")
    processing_log: List[dict]
    requested_mode: str
    mode_reason: str
    chat_history: List[dict] = Field(default_factory=list)


class EvidenceInput(BaseModel):
    document_id: str
    page_or_sheet: str
    exact_quote: str


class ManualAdjustmentInput(BaseModel):
    title: str = Field(..., min_length=3)
    category: AdjustmentCategory = "OTHER"
    period: str
    amount_cop: float
    rationale: str = Field(..., min_length=3)
    status: AdjustmentStatus = "ACCEPTED"
    evidence: Optional[EvidenceInput] = Field(
        None, description="Cita a un documento del deal. Si se omite, la fuente es la nota del analista."
    )


class RecalculateRequest(BaseModel):
    adjustment_statuses: Dict[str, AdjustmentStatus] = Field(default_factory=dict)
    manual_adjustments: List[ManualAdjustmentInput] = Field(default_factory=list)
    remove_adjustment_ids: List[str] = Field(default_factory=list, description="Solo ajustes manuales del analista.")
    red_flag_statuses: Dict[str, Literal["ACTIVE", "DISMISSED"]] = Field(default_factory=dict)
    persist: bool = True


class RecalculateResponse(BaseModel):
    deal_id: str
    ebitda_adjustments: List[EbitdaAdjustment]
    red_flags: List[RedFlagItem]
    financials: FinancialEngineResult
    memo_markdown: str
    computation_ms: float
    persisted: bool


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class KeyMetrics(BaseModel):
    period: str
    ebitda_adjusted_cop: float
    ebitda_adjusted_margin_pct: Optional[float]
    net_debt_to_ebitda_adjusted: Optional[float]
    base_enterprise_value_cop: Optional[float]
    base_equity_value_cop: Optional[float]


class ScenarioResult(BaseModel):
    overrides: Dict[str, AdjustmentStatus]
    description: str
    before: KeyMetrics
    after: KeyMetrics


class ChatResponse(BaseModel):
    answer_markdown: str
    citations: List[SourceCitation]
    scenario: Optional[ScenarioResult] = None
    mode: str


class PipelineStep(BaseModel):
    node: str
    label: str
    state: Literal["pending", "running", "done", "failed"]


class JobStatus(BaseModel):
    """Progreso del procesamiento asíncrono de una operación."""

    deal_id: str
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED"]
    requested_mode: str
    effective_mode: str
    mode_reason: str
    document_names: List[str]
    progress_pct: int
    current_node: Optional[str]
    current_message: str
    steps: List[PipelineStep]
    events: List[dict]
    llm_calls: int
    error: Optional[str]
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]
    elapsed_s: float


class LlmStatus(BaseModel):
    cloud_model: Optional[str]
    cloud_available: bool
    ollama_model: str
    ollama_base_url: str
    ollama_available: bool
    ollama_installed_models: List[str] = Field(default_factory=list)
