import type {
  ChatResponse,
  DealSummary,
  DealView,
  LlmStatus,
  RecalculateRequest,
  RecalculateResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("No hay conexión con el backend. ¿Está corriendo uvicorn en el puerto 8000?", 0);
  }
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      if (response.status >= 500) detail = "El backend no respondió correctamente (¿está corriendo?).";
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

function json(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  listDeals: () => request<DealSummary[]>("/api/deals"),
  getDeal: (id: string) => request<DealView>(`/api/deals/${encodeURIComponent(id)}`),
  llmStatus: () => request<LlmStatus>("/api/llm/status"),
  createDemo: () => {
    const form = new FormData();
    form.append("use_demo", "true");
    return request<DealView>("/api/deals/upload", { method: "POST", body: form });
  },
  uploadDeal: (files: File[], llmMode: "CLOUD_API" | "LOCAL_OLLAMA", hints: { company_name?: string; nit?: string; ciiu_code?: string }) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("llm_mode", llmMode);
    Object.entries(hints).forEach(([k, v]) => v && form.append(k, v));
    return request<DealView>("/api/deals/upload", { method: "POST", body: form });
  },
  recalculate: (id: string, body: RecalculateRequest) =>
    request<RecalculateResponse>(`/api/deals/${encodeURIComponent(id)}/recalculate`, json(body)),
  chat: (id: string, message: string) => request<ChatResponse>(`/api/deals/${encodeURIComponent(id)}/chat`, json({ message })),
};
