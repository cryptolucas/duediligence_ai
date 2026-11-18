import type {
  ChatResponse,
  DealSummary,
  DealView,
  DocumentValidation,
  JobStatus,
  LlmStatus,
  RecalculateRequest,
  RecalculateResponse,
  UploadIssue,
  UploadRequirements,
  UploadSlotId,
} from "./types";

/**
 * URL del backend. En local se deja vacía y Next.js reenvía /api al backend (ver next.config.mjs).
 * En producción (Vercel) se define NEXT_PUBLIC_API_BASE_URL=https://<servicio>.onrender.com y el navegador llama
 * directo al backend: sin el límite de 120 s ni de tamaño del proxy de Vercel.
 */
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

const WORKSPACE_KEY = "catalejo.workspace";
const ACCESS_CODE_KEY = "catalejo.accessCode";
export const AUTH_REQUIRED_EVENT = "catalejo:auth-required";
export const SERVER_WAKING_EVENT = "catalejo:server-waking";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public issues: UploadIssue[] = [],
  ) {
    super(message);
  }
}

function storageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* modo privado o almacenamiento bloqueado: se sigue sin persistir */
  }
}

let memoryWorkspace: string | null = null;

/** Identificador aleatorio de este navegador: cada persona ve solo sus operaciones en la lista. */
export function workspaceId(): string {
  if (typeof window === "undefined") return "";
  let id = storageGet(WORKSPACE_KEY) ?? memoryWorkspace;
  if (!id) {
    id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
    memoryWorkspace = id;
    storageSet(WORKSPACE_KEY, id);
  }
  return id;
}

export function getAccessCode(): string | null {
  return typeof window === "undefined" ? null : storageGet(ACCESS_CODE_KEY);
}

export function setAccessCode(code: string | null) {
  storageSet(ACCESS_CODE_KEY, code);
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  const ws = workspaceId();
  if (ws) h.set("X-Workspace-Id", ws);
  const code = getAccessCode();
  if (code) h.set("X-Access-Code", code);
  return h;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const STATUS_MESSAGES: Record<number, string> = {
  401: "Necesita el código de acceso de la prueba.",
  404: "No encontramos lo que busca. Puede que el enlace sea incorrecto o que la operación se haya eliminado.",
  413: "Los archivos son demasiado grandes. Cada archivo puede pesar máximo 25 MB.",
  429: "Hay muchas solicitudes en este momento. Espere un minuto e intente de nuevo.",
  502: "El servidor se está iniciando o reiniciando. Espere un momento e intente de nuevo.",
  503: "El servidor se está iniciando o reiniciando. Espere un momento e intente de nuevo.",
  504: "El servidor tardó demasiado en responder. Intente de nuevo en un momento.",
};

async function request<T>(path: string, init?: RequestInit & { retries?: number }): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  // Las lecturas se reintentan: en el plan gratuito el servidor "duerme" y tarda hasta ~1 minuto en despertar.
  const retries = init?.retries ?? (method === "GET" ? 4 : 0);
  let response: Response | null = null;
  for (let attempt = 0; ; attempt++) {
    try {
      response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init, headers: headers(init?.headers) });
      if ([502, 503, 504].includes(response.status) && attempt < retries) throw new Error("waking");
      break;
    } catch {
      if (attempt >= retries) {
        throw new ApiError(
          "No pudimos conectar con el servidor. Revise su conexión a internet; si el servidor estaba inactivo puede tardar hasta un minuto en despertar. Intente de nuevo.",
          0,
        );
      }
      if (typeof window !== "undefined") window.dispatchEvent(new Event(SERVER_WAKING_EVENT));
      await sleep(Math.min(15000, 3000 * (attempt + 1)));
    }
  }
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
  }
  if (!response.ok) {
    let detail = STATUS_MESSAGES[response.status] ?? `Error ${response.status}`;
    let issues: UploadIssue[] = [];
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
      else if (body.detail && typeof body.detail === "object") {
        detail = body.detail.message ?? detail;
        issues = body.detail.issues ?? [];
      }
    } catch {
      if (response.status >= 500 && !STATUS_MESSAGES[response.status]) detail = "El servidor tuvo un problema. Intente de nuevo en un momento.";
    }
    throw new ApiError(detail, response.status, issues);
  }
  return response.json() as Promise<T>;
}

function json(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const SLOT_FORM_FIELD: Record<UploadSlotId, string> = {
  TRIAL_BALANCE: "trial_balance_files",
  FINANCIAL_STATEMENTS: "financial_statements_files",
  CHAMBER_CERTIFICATE: "chamber_certificate_files",
  OTHER: "other_files",
};

export interface Health {
  status: string;
  version: string;
  access_code_required: boolean;
}

export const api = {
  health: () => request<Health>("/api/health", { retries: 8 }),
  listDeals: () => request<DealSummary[]>("/api/deals"),
  getDeal: (id: string) => request<DealView>(`/api/deals/${encodeURIComponent(id)}`),
  llmStatus: () => request<LlmStatus>("/api/llm/status"),
  uploadRequirements: () => request<UploadRequirements>("/api/upload-requirements"),
  createDemo: () => {
    const form = new FormData();
    form.append("use_demo", "true");
    return request<DealView>("/api/deals/upload", { method: "POST", body: form });
  },
  /** Valida un archivo para una casilla (no crea la operación). */
  validateDocument: (file: File, slot: UploadSlotId) => {
    const form = new FormData();
    form.append("file", file);
    form.append("slot", slot);
    return request<DocumentValidation>("/api/documents/validate", { method: "POST", body: form, retries: 1 });
  },
  /** Valida y parsea los archivos por casilla; el grafo de agentes sigue en segundo plano (202 + estado del job). */
  uploadDeal: (
    filesBySlot: Record<UploadSlotId, File[]>,
    llmMode: "CLOUD_API" | "LOCAL_OLLAMA",
    hints: { company_name?: string; nit?: string; ciiu_code?: string },
  ) => {
    const form = new FormData();
    (Object.keys(filesBySlot) as UploadSlotId[]).forEach((slot) =>
      filesBySlot[slot].forEach((f) => form.append(SLOT_FORM_FIELD[slot], f)),
    );
    form.append("llm_mode", llmMode);
    Object.entries(hints).forEach(([k, v]) => v && v.trim() && form.append(k, v.trim()));
    return request<JobStatus>("/api/deals/upload", { method: "POST", body: form });
  },
  getStatus: (id: string) => request<JobStatus>(`/api/deals/${encodeURIComponent(id)}/status`),
  listJobs: () => request<JobStatus[]>("/api/jobs"),
  recalculate: (id: string, body: RecalculateRequest) =>
    request<RecalculateResponse>(`/api/deals/${encodeURIComponent(id)}/recalculate`, json(body)),
  chat: (id: string, message: string) => request<ChatResponse>(`/api/deals/${encodeURIComponent(id)}/chat`, json({ message })),
};
