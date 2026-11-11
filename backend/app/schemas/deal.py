"""Esquemas centrales del Expediente de Inversión (Pydantic v2).

Regla de oro (Zero Uncited Claims): toda cifra, ajuste, red flag o afirmación que
provenga de un documento lleva un ``SourceCitation``. Lo que no tiene fuente se
representa explícitamente con estado ``MISSING_DATA`` — nunca se inventa.

Convención de signos para ``MappedAccountItem.raw_value_cop`` (valores en COP plenos):

* REVENUE ........................ positivo aumenta ingresos (devoluciones 4175 van negativas).
* COGS, SGA, DA, TAXES ........... positivo = gasto/costo (reversiones van negativas).
* OTHER_OP_INCOME_EXP ............ positivo = ingreso operativo, negativo = gasto operativo.
* NET_INTEREST ................... positivo = gasto financiero neto (ingresos financieros negativos).
* Activos ........................ positivo; cuentas correctoras (1399, 1592) negativas.
* Pasivos y EQUITY ............... positivo; pérdidas acumuladas negativas.
* UNMAPPED ....................... se reporta pero el motor lo excluye de todo cálculo.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Tipos literales compartidos
# ---------------------------------------------------------------------------

StandardCategory = Literal[
    "REVENUE",
    "COGS",
    "SGA",
    "DA",
    "OTHER_OP_INCOME_EXP",
    "NET_INTEREST",
    "TAXES",
    "CASH",
    "ACCOUNTS_RECEIVABLE",
    "INVENTORY",
    "OTHER_CURRENT_ASSETS",
    "PPE_AND_INTANGIBLES",
    "ACCOUNTS_PAYABLE",
    "SHORT_TERM_DEBT",
    "OTHER_CURRENT_LIABILITIES",
    "LONG_TERM_DEBT",
    "EQUITY",
    "UNMAPPED",
]

INCOME_STATEMENT_CATEGORIES: tuple[str, ...] = (
    "REVENUE",
    "COGS",
    "SGA",
    "DA",
    "OTHER_OP_INCOME_EXP",
    "NET_INTEREST",
    "TAXES",
)
ASSET_CATEGORIES: tuple[str, ...] = (
    "CASH",
    "ACCOUNTS_RECEIVABLE",
    "INVENTORY",
    "OTHER_CURRENT_ASSETS",
    "PPE_AND_INTANGIBLES",
)
LIABILITY_CATEGORIES: tuple[str, ...] = (
    "ACCOUNTS_PAYABLE",
    "SHORT_TERM_DEBT",
    "OTHER_CURRENT_LIABILITIES",
    "LONG_TERM_DEBT",
)
EQUITY_CATEGORIES: tuple[str, ...] = ("EQUITY",)

AdjustmentCategory = Literal[
    "OWNER_COMPENSATION",
    "RELATED_PARTY_RENT",
    "NON_RECURRING_LEGAL",
    "PERSONAL_EXPENSES",
    "OTHER",
]
AdjustmentStatus = Literal["ACCEPTED", "REJECTED", "PENDING_REVIEW"]
RedFlagSeverity = Literal["CRITICAL_DEALBREAKER", "HIGH", "MEDIUM"]
RedFlagDomain = Literal["FINANCIAL", "CORPORATE_LEGAL", "TAX_AND_CONTINGENCIES", "COMMERCIAL_MARKET"]
# CLOUD_API / LOCAL_OLLAMA: agentes LLM activos. SEED_FALLBACK: caso demo precargado.
# RULES_FALLBACK: documentos propios procesados solo con reglas deterministas (sin claves o sin Ollama).
LlmMode = Literal["CLOUD_API", "LOCAL_OLLAMA", "SEED_FALLBACK", "RULES_FALLBACK"]

ANALYST_INPUT_DOCUMENT_ID = "analyst_input"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Trazabilidad
# ---------------------------------------------------------------------------


class SourceCitation(_StrictModel):
    """Ancla documental de un dato: documento, página/hoja, celda/línea y cita literal."""

    citation_id: str = Field(..., description="Identificador único de la cita dentro del deal (ej. 'cit_bp25_4120').")
    document_id: str
    document_name: str
    page_or_sheet: str = Field(..., description="Ej: 'Página 4' o 'BP_2025'.")
    cell_or_line_ref: Optional[str] = Field(
        default=None, description="Celda ('C18') o línea/renglón ('Línea 12') dentro de la página u hoja."
    )
    exact_quote: str = Field(..., min_length=1, description="Fragmento literal o celda cruda extraída.")
    confidence: float = Field(..., ge=0.0, le=1.0)


class LineBox(_StrictModel):
    """Coordenadas (puntos PDF, origen arriba-izquierda) de una línea del contenido extraído."""

    line: int = Field(..., ge=1, description="Número de línea (1-based) dentro de DocumentPage.content.")
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentPage(_StrictModel):
    page_or_sheet: str
    content: str = Field(..., description="Texto extraído de la página u hoja (filas serializadas para Excel).")
    width: Optional[float] = None
    height: Optional[float] = None
    line_boxes: List[LineBox] = Field(default_factory=list, description="Coordenadas por línea (solo PDF).")


class SourceDocument(_StrictModel):
    document_id: str
    document_name: str
    document_type: Literal[
        "FINANCIAL_STATEMENTS_PDF",
        "TRIAL_BALANCE_XLSX",
        "CHAMBER_OF_COMMERCE_CERT",
        "TEASER",
        "APPRAISAL",
        "OTHER",
    ]
    file_format: Literal["PDF", "XLSX", "CSV"]
    description: str
    reported_units: str = Field(..., description="Unidades del documento original, ej. 'Miles de COP' o 'COP'.")
    pages: List[DocumentPage]


class CitedFact(_StrictModel):
    """Hecho cualitativo (texto) anclado a una fuente o marcado explícitamente como faltante."""

    label: str
    value: Optional[str] = None
    status: Literal["VERIFIED", "UNVERIFIED", "MISSING_DATA"]
    citation: Optional[SourceCitation] = None

    @model_validator(mode="after")
    def _citation_required_unless_missing(self) -> "CitedFact":
        if self.status == "MISSING_DATA":
            if self.value is not None:
                raise ValueError(f"CitedFact '{self.label}': MISSING_DATA no puede traer valor.")
        elif self.citation is None:
            raise ValueError(f"CitedFact '{self.label}': todo dato con valor requiere SourceCitation.")
        return self


# ---------------------------------------------------------------------------
# Esquemas centrales (especificación)
# ---------------------------------------------------------------------------


class MappedAccountItem(_StrictModel):
    raw_account_code: Optional[str] = Field(default=None, description="Código PUC colombiano, ej. '4135', '5105'.")
    raw_account_name: str
    standard_category: StandardCategory
    period: str = Field(..., description="Ej: '2023', '2024', '2025'.")
    raw_value_cop: float = Field(..., description="Valor en COP plenos según la convención de signos del módulo.")
    mapping_rationale: str
    citation: SourceCitation


class EbitdaAdjustment(_StrictModel):
    id: str
    title: str
    category: AdjustmentCategory
    period: str
    amount_cop: float = Field(..., description="COP a sumar (positivo) o restar (negativo) al EBITDA reportado.")
    rationale: str
    status: AdjustmentStatus = "ACCEPTED"
    citation: SourceCitation
    origin: Literal["AI_PROPOSED", "ANALYST_MANUAL"] = "AI_PROPOSED"


class RedFlagItem(_StrictModel):
    id: str
    severity: RedFlagSeverity
    domain: RedFlagDomain
    title: str
    challenge_by_skeptic: str
    mitigation_question: str
    status: Literal["ACTIVE", "DISMISSED"] = "ACTIVE"
    citations: List[SourceCitation] = Field(..., min_length=1)


class MissingInfoItem(_StrictModel):
    id: str
    category: str
    requested_document_or_clarification: str
    why_it_matters_plain_spanish: str
    priority: Literal["MUST_HAVE_FOR_IC", "NICE_TO_HAVE"]


# ---------------------------------------------------------------------------
# Perfil societario y contingencias
# ---------------------------------------------------------------------------


class Shareholder(_StrictModel):
    name: str
    ownership_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Porcentaje tal como lo reporta la fuente.")
    verification_status: Literal["VERIFIED", "UNVERIFIED", "MISSING_DATA"]
    citation: Optional[SourceCitation] = None

    @model_validator(mode="after")
    def _citation_required(self) -> "Shareholder":
        if self.verification_status != "MISSING_DATA" and self.citation is None:
            raise ValueError(f"Accionista '{self.name}' sin SourceCitation debe marcarse MISSING_DATA.")
        return self


class LegalProceeding(_StrictModel):
    """Litigio o proceso (laboral, tributario, etc.) revelado en notas o certificados."""

    id: str
    proceeding_type: Literal["LABORAL", "TRIBUTARIO", "CIVIL_COMERCIAL", "ADMINISTRATIVO"]
    description: str
    claimed_amount_cop: Optional[float] = Field(default=None, ge=0.0)
    provisioned_amount_cop: float = Field(default=0.0, ge=0.0)
    probability: Literal["PROBABLE", "POSIBLE", "REMOTA", "NO_INFORMADA"]
    citation: SourceCitation


# Alias semántico: el motor trata los procesos legales como contingencias.
ContingencyItem = LegalProceeding


class CorporateProfile(_StrictModel):
    legal_name: CitedFact
    nit: CitedFact
    ciiu_primary: CitedFact
    ciiu_secondary: CitedFact
    domicile: CitedFact
    incorporation: CitedFact
    legal_representative: CitedFact
    alternate_legal_representative: CitedFact
    statutory_limits: List[CitedFact]
    shareholders: List[Shareholder]
    legal_proceedings: List[LegalProceeding]


class UnreadableItem(_StrictModel):
    id: str
    description: str
    reason: str
    citation: Optional[SourceCitation] = None


# ---------------------------------------------------------------------------
# Expediente completo
# ---------------------------------------------------------------------------


class DealDossier(_StrictModel):
    deal_id: str
    created_at: datetime
    llm_mode: LlmMode
    company_name: str
    nit: str
    ciiu_code: str
    city: str
    periods: List[str] = Field(..., min_length=1)
    pre_closing_trial_balance_periods: List[str] = Field(
        default_factory=list,
        description=(
            "Periodos cuyo balance de prueba es pre-cierre (cuentas de resultado abiertas, sin 3605). "
            "El motor suma el resultado del ejercicio calculado al patrimonio al validar la ecuación contable."
        ),
    )
    documents: List[SourceDocument]
    mapped_accounts: List[MappedAccountItem]
    unreadable_or_unmapped_items: List[UnreadableItem] = Field(default_factory=list)
    ebitda_adjustments: List[EbitdaAdjustment]
    corporate_profile: CorporateProfile
    red_flags: List[RedFlagItem]
    missing_info: List[MissingInfoItem]
    memo_markdown_template: str = Field(
        ...,
        description=(
            "Memo redactado por el agente con marcadores: [[cite:<citation_id>]] para fuentes y "
            "{{metric:<nombre>:<periodo>}} / {{valuation:<escenario>:<campo>}} que el renderizador "
            "determinista reemplaza con salidas del motor financiero."
        ),
    )
    memo_citations: List[SourceCitation] = Field(
        default_factory=list,
        description="Citas usadas solo por el memo (afirmaciones cualitativas que no viven en otro objeto).",
    )

    @model_validator(mode="after")
    def _validate_integrity(self) -> "DealDossier":
        doc_ids = {d.document_id for d in self.documents} | {ANALYST_INPUT_DOCUMENT_ID}
        periods = set(self.periods)
        for citation in self.iter_citations():
            if citation.document_id not in doc_ids:
                raise ValueError(f"Cita {citation.citation_id} apunta a documento inexistente {citation.document_id}.")
        for item in self.mapped_accounts:
            if item.period not in periods:
                raise ValueError(f"Cuenta {item.raw_account_name} con periodo desconocido {item.period}.")
        for adj in self.ebitda_adjustments:
            if adj.period not in periods:
                raise ValueError(f"Ajuste {adj.id} con periodo desconocido {adj.period}.")
        adj_ids = [a.id for a in self.ebitda_adjustments]
        if len(adj_ids) != len(set(adj_ids)):
            raise ValueError("IDs de ajustes de EBITDA duplicados.")
        return self

    def iter_citations(self):
        """Recorre todas las citas del expediente (para auditoría y para el inspector de evidencia)."""
        for item in self.mapped_accounts:
            yield item.citation
        for adj in self.ebitda_adjustments:
            yield adj.citation
        for flag in self.red_flags:
            yield from flag.citations
        for item in self.unreadable_or_unmapped_items:
            if item.citation is not None:
                yield item.citation
        profile = self.corporate_profile
        for fact in (
            profile.legal_name,
            profile.nit,
            profile.ciiu_primary,
            profile.ciiu_secondary,
            profile.domicile,
            profile.incorporation,
            profile.legal_representative,
            profile.alternate_legal_representative,
            *profile.statutory_limits,
        ):
            if fact.citation is not None:
                yield fact.citation
        for holder in profile.shareholders:
            if holder.citation is not None:
                yield holder.citation
        for proceeding in profile.legal_proceedings:
            yield proceeding.citation
        yield from self.memo_citations

    def citation_index(self) -> dict[str, SourceCitation]:
        return {c.citation_id: c for c in self.iter_citations()}
