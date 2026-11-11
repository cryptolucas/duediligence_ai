// Formato de presentación (es-CO). La aritmética financiera vive en el backend; aquí solo
// se cambian unidades de visualización (COP millones / USD con una TRM explícita).

export type DisplayUnit = "COP_M" | "USD";

const nf = (digits: number) =>
  new Intl.NumberFormat("es-CO", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function formatMoney(valueCop: number | null | undefined, unit: DisplayUnit, trm: number, opts: { parens?: boolean } = {}): string {
  if (valueCop === null || valueCop === undefined || Number.isNaN(valueCop)) return "n/d";
  const scaled = unit === "COP_M" ? valueCop / 1_000_000 : valueCop / trm / 1_000_000;
  const digits = unit === "COP_M" ? 0 : 2;
  const text = nf(digits).format(Math.abs(scaled));
  if (scaled < 0) return opts.parens ? `(${text})` : `-${text}`;
  return text;
}

export function moneyWithUnit(valueCop: number | null | undefined, unit: DisplayUnit, trm: number): string {
  const body = formatMoney(valueCop, unit, trm);
  if (body === "n/d") return body;
  return unit === "COP_M" ? `COP ${body} M` : `USD ${body} M`;
}

export function unitLabel(unit: DisplayUnit): string {
  return unit === "COP_M" ? "COP millones" : "USD millones";
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "n/d";
  return `${nf(digits).format(value)} %`;
}

export function formatMultiple(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/s";
  return `${nf(2).format(value)}x`;
}

export function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/d";
  return nf(0).format(value);
}

export function shortDocName(name: string): string {
  const base = name.replace(/\.(pdf|xlsx|xlsm|csv)$/i, "");
  return base.length > 26 ? `${base.slice(0, 24)}…` : base;
}

export function shortPage(page: string): string {
  return page.replace(/^Página\s+/i, "Pág. ");
}

export const SEVERITY_LABEL = { CRITICAL_DEALBREAKER: "Crítico", HIGH: "Alto", MEDIUM: "Medio" } as const;
export const DOMAIN_LABEL = {
  FINANCIAL: "Financiero",
  CORPORATE_LEGAL: "Societario / legal",
  TAX_AND_CONTINGENCIES: "Tributario y contingencias",
  COMMERCIAL_MARKET: "Comercial / mercado",
} as const;
export const ADJ_CATEGORY_LABEL = {
  OWNER_COMPENSATION: "Compensación de socios",
  RELATED_PARTY_RENT: "Arriendo a vinculados",
  NON_RECURRING_LEGAL: "Legal no recurrente",
  PERSONAL_EXPENSES: "Gastos personales",
  OTHER: "Otro",
} as const;
export const MODE_LABEL = {
  CLOUD_API: "LLM en la nube",
  LOCAL_OLLAMA: "LLM local (Ollama)",
  SEED_FALLBACK: "Caso demo",
  RULES_FALLBACK: "Reglas deterministas",
} as const;
