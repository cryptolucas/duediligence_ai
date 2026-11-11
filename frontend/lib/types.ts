// Tipos espejo de los esquemas Pydantic del backend (app/schemas/*.py).

export type StandardCategory =
  | "REVENUE" | "COGS" | "SGA" | "DA" | "OTHER_OP_INCOME_EXP" | "NET_INTEREST" | "TAXES"
  | "CASH" | "ACCOUNTS_RECEIVABLE" | "INVENTORY" | "OTHER_CURRENT_ASSETS" | "PPE_AND_INTANGIBLES"
  | "ACCOUNTS_PAYABLE" | "SHORT_TERM_DEBT" | "OTHER_CURRENT_LIABILITIES" | "LONG_TERM_DEBT" | "EQUITY" | "UNMAPPED";

export type AdjustmentCategory = "OWNER_COMPENSATION" | "RELATED_PARTY_RENT" | "NON_RECURRING_LEGAL" | "PERSONAL_EXPENSES" | "OTHER";
export type AdjustmentStatus = "ACCEPTED" | "REJECTED" | "PENDING_REVIEW";
export type Severity = "CRITICAL_DEALBREAKER" | "HIGH" | "MEDIUM";
export type Domain = "FINANCIAL" | "CORPORATE_LEGAL" | "TAX_AND_CONTINGENCIES" | "COMMERCIAL_MARKET";
export type LlmMode = "CLOUD_API" | "LOCAL_OLLAMA" | "SEED_FALLBACK" | "RULES_FALLBACK";

export interface SourceCitation {
  citation_id: string;
  document_id: string;
  document_name: string;
  page_or_sheet: string;
  cell_or_line_ref: string | null;
  exact_quote: string;
  confidence: number;
}

export interface LineBox { line: number; x0: number; y0: number; x1: number; y1: number }

export interface DocumentPage {
  page_or_sheet: string;
  content: string;
  width?: number | null;
  height?: number | null;
  line_boxes?: LineBox[];
}

export interface SourceDocument {
  document_id: string;
  document_name: string;
  document_type: "FINANCIAL_STATEMENTS_PDF" | "TRIAL_BALANCE_XLSX" | "CHAMBER_OF_COMMERCE_CERT" | "TEASER" | "APPRAISAL" | "OTHER";
  file_format: "PDF" | "XLSX" | "CSV";
  description: string;
  reported_units: string;
  pages: DocumentPage[];
}

export interface CitedFact {
  label: string;
  value: string | null;
  status: "VERIFIED" | "UNVERIFIED" | "MISSING_DATA";
  citation: SourceCitation | null;
}

export interface MappedAccountItem {
  raw_account_code: string | null;
  raw_account_name: string;
  standard_category: StandardCategory;
  period: string;
  raw_value_cop: number;
  mapping_rationale: string;
  citation: SourceCitation;
}

export interface EbitdaAdjustment {
  id: string;
  title: string;
  category: AdjustmentCategory;
  period: string;
  amount_cop: number;
  rationale: string;
  status: AdjustmentStatus;
  citation: SourceCitation;
  origin: "AI_PROPOSED" | "ANALYST_MANUAL";
}

export interface RedFlagItem {
  id: string;
  severity: Severity;
  domain: Domain;
  title: string;
  challenge_by_skeptic: string;
  mitigation_question: string;
  status: "ACTIVE" | "DISMISSED";
  citations: SourceCitation[];
}

export interface MissingInfoItem {
  id: string;
  category: string;
  requested_document_or_clarification: string;
  why_it_matters_plain_spanish: string;
  priority: "MUST_HAVE_FOR_IC" | "NICE_TO_HAVE";
}

export interface Shareholder {
  name: string;
  ownership_pct: number | null;
  verification_status: "VERIFIED" | "UNVERIFIED" | "MISSING_DATA";
  citation: SourceCitation | null;
}

export interface LegalProceeding {
  id: string;
  proceeding_type: "LABORAL" | "TRIBUTARIO" | "CIVIL_COMERCIAL" | "ADMINISTRATIVO";
  description: string;
  claimed_amount_cop: number | null;
  provisioned_amount_cop: number;
  probability: "PROBABLE" | "POSIBLE" | "REMOTA" | "NO_INFORMADA";
  citation: SourceCitation;
}

export interface CorporateProfile {
  legal_name: CitedFact;
  nit: CitedFact;
  ciiu_primary: CitedFact;
  ciiu_secondary: CitedFact;
  domicile: CitedFact;
  incorporation: CitedFact;
  legal_representative: CitedFact;
  alternate_legal_representative: CitedFact;
  statutory_limits: CitedFact[];
  shareholders: Shareholder[];
  legal_proceedings: LegalProceeding[];
}

export interface UnreadableItem {
  id: string;
  description: string;
  reason: string;
  citation: SourceCitation | null;
}

export interface DealDossier {
  deal_id: string;
  created_at: string;
  llm_mode: LlmMode;
  company_name: string;
  nit: string;
  ciiu_code: string;
  city: string;
  periods: string[];
  pre_closing_trial_balance_periods: string[];
  documents: SourceDocument[];
  mapped_accounts: MappedAccountItem[];
  unreadable_or_unmapped_items: UnreadableItem[];
  ebitda_adjustments: EbitdaAdjustment[];
  corporate_profile: CorporateProfile;
  red_flags: RedFlagItem[];
  missing_info: MissingInfoItem[];
  memo_markdown_template: string;
  memo_citations: SourceCitation[];
}

// ---------------------------------------------------------------- Motor financiero

export interface TracedValue { value_cop: number; source_citation_ids: string[] }

export interface IncomeStatementMetrics {
  period: string;
  revenue: TracedValue;
  cogs: TracedValue;
  gross_profit_cop: number;
  sga: TracedValue;
  other_operating_income_expense: TracedValue;
  ebitda_reported_cop: number;
  depreciation_amortization: TracedValue;
  ebit_cop: number;
  net_interest: TracedValue;
  pre_tax_income_cop: number;
  taxes: TracedValue;
  net_income_cop: number;
  revenue_growth_yoy_pct: number | null;
  gross_margin_pct: number | null;
  ebitda_reported_margin_pct: number | null;
  ebitda_adjusted_cop: number;
  ebitda_adjusted_margin_pct: number | null;
  net_margin_pct: number | null;
}

export interface BalanceCheck {
  period: string;
  total_assets_cop: number;
  total_liabilities_cop: number;
  total_equity_cop: number;
  current_year_result_included_cop: number;
  difference_cop: number;
  is_balanced: boolean;
  tolerance_cop: number;
}

export interface BalanceSheetMetrics {
  period: string;
  cash: TracedValue;
  accounts_receivable: TracedValue;
  inventory: TracedValue;
  other_current_assets: TracedValue;
  ppe_and_intangibles: TracedValue;
  total_current_assets_cop: number;
  total_assets_cop: number;
  accounts_payable: TracedValue;
  short_term_debt: TracedValue;
  other_current_liabilities: TracedValue;
  long_term_debt: TracedValue;
  total_current_liabilities_cop: number;
  total_liabilities_cop: number;
  equity: TracedValue;
  balance_check: BalanceCheck;
}

export interface WorkingCapitalMetrics {
  period: string;
  net_working_capital_cop: number;
  nwc_pct_of_revenue: number | null;
  dso_days: number | null;
  dio_days: number | null;
  dpo_days: number | null;
  cash_conversion_cycle_days: number | null;
  current_ratio: number | null;
}

export interface LeverageMetrics {
  period: string;
  gross_financial_debt_cop: number;
  net_financial_debt_cop: number;
  net_debt_to_ebitda_reported: number | null;
  net_debt_to_ebitda_adjusted: number | null;
  interest_coverage_ebitda_adjusted: number | null;
}

export interface BridgeLine {
  adjustment_id: string;
  title: string;
  category: string;
  amount_cop: number;
  status: AdjustmentStatus;
  included: boolean;
  origin: string;
  citation_id: string;
}

export interface EbitdaBridge {
  period: string;
  ebitda_reported_cop: number;
  lines: BridgeLine[];
  total_accepted_adjustments_cop: number;
  total_pending_adjustments_cop: number;
  total_rejected_adjustments_cop: number;
  ebitda_adjusted_cop: number;
}

export interface ValuationScenario {
  scenario: "CONSERVADOR" | "BASE" | "OPTIMISTA";
  percentile: "P25" | "MEDIANA" | "P75";
  ev_ebitda_multiple: number;
  enterprise_value_cop: number;
  net_financial_debt_cop: number;
  equity_value_cop: number;
  implied_ev_revenue: number | null;
}

export interface ValuationResult {
  status: "OK" | "MISSING_DATA" | "NOT_MEANINGFUL";
  valuation_period: string;
  ciiu_code: string;
  sector_key: string | null;
  sector_label: string | null;
  benchmark_status: string | null;
  ebitda_basis_cop: number | null;
  scenarios: ValuationScenario[];
  sector_operating_benchmarks: Record<string, Record<string, number>>;
  message: string | null;
}

export interface ContingencyExposure {
  total_claimed_cop: number;
  total_provisioned_cop: number;
  unprovisioned_probable_or_possible_cop: number;
  unprovisioned_pct_of_adjusted_ebitda: number | null;
  unprovisioned_pct_of_base_equity_value: number | null;
  proceeding_ids: string[];
}

export interface EngineWarning { code: string; period: string | null; message: string }

export interface FinancialEngineResult {
  engine_version: string;
  llm_calls: number;
  periods: string[];
  income_statement: IncomeStatementMetrics[];
  balance_sheet: BalanceSheetMetrics[];
  working_capital: WorkingCapitalMetrics[];
  leverage: LeverageMetrics[];
  ebitda_bridge: EbitdaBridge[];
  growth: { first_period: string; last_period: string; revenue_cagr_pct: number | null; ebitda_adjusted_cagr_pct: number | null };
  valuation: ValuationResult;
  contingencies: ContingencyExposure;
  unmapped_account_count: number;
  warnings: EngineWarning[];
  computation_ms: number;
}

// ---------------------------------------------------------------- API

export interface ProcessingLogEntry {
  node: string;
  mode: string;
  duration_ms: number;
  llm_calls: number;
  message: string;
  notes?: string[];
}

export interface ChatHistoryEntry { role: "user" | "assistant"; content: string; mode?: string }

export interface DealView {
  dossier: DealDossier;
  financials: FinancialEngineResult;
  memo_markdown: string;
  processing_log: ProcessingLogEntry[];
  requested_mode: string;
  mode_reason: string;
  chat_history: ChatHistoryEntry[];
}

export interface DealSummary {
  deal_id: string;
  company_name: string;
  nit: string;
  ciiu_code: string;
  llm_mode: LlmMode;
  requested_mode: string;
  created_at: string;
  updated_at: string;
  periods: string[];
  last_period: string;
  revenue_last_cop: number;
  ebitda_adjusted_last_cop: number;
  all_balances_tie: boolean;
  red_flags_by_severity: Partial<Record<Severity, number>>;
}

export interface ManualAdjustmentInput {
  title: string;
  category: AdjustmentCategory;
  period: string;
  amount_cop: number;
  rationale: string;
  status?: AdjustmentStatus;
  evidence?: { document_id: string; page_or_sheet: string; exact_quote: string } | null;
}

export interface RecalculateRequest {
  adjustment_statuses?: Record<string, AdjustmentStatus>;
  manual_adjustments?: ManualAdjustmentInput[];
  remove_adjustment_ids?: string[];
  red_flag_statuses?: Record<string, "ACTIVE" | "DISMISSED">;
  persist?: boolean;
}

export interface RecalculateResponse {
  deal_id: string;
  ebitda_adjustments: EbitdaAdjustment[];
  red_flags: RedFlagItem[];
  financials: FinancialEngineResult;
  memo_markdown: string;
  computation_ms: number;
  persisted: boolean;
}

export interface KeyMetrics {
  period: string;
  ebitda_adjusted_cop: number;
  ebitda_adjusted_margin_pct: number | null;
  net_debt_to_ebitda_adjusted: number | null;
  base_enterprise_value_cop: number | null;
  base_equity_value_cop: number | null;
}

export interface ChatResponse {
  answer_markdown: string;
  citations: SourceCitation[];
  scenario: { overrides: Record<string, AdjustmentStatus>; description: string; before: KeyMetrics; after: KeyMetrics } | null;
  mode: string;
}

export interface LlmStatus {
  cloud_model: string | null;
  cloud_available: boolean;
  ollama_model: string;
  ollama_base_url: string;
  ollama_available: boolean;
  ollama_installed_models: string[];
}
