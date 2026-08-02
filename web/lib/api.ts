import { PYTHON_SERVICE_URL } from "./supabase";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = PYTHON_SERVICE_URL.replace(/\/$/, "") + path;
  const isForm = init?.body instanceof FormData;
  const res = await fetch(url, {
    headers: isForm
      ? undefined
      : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => (d && typeof d === "object" && "msg" in d ? d.msg : String(d))).join("; ")
          : JSON.stringify(detail)
    );
  }
  return res.json() as Promise<T>;
}

export type ChatResponse = {
  question: string;
  answer: string;
  blocked: boolean;
  block_reason: string;
  risk: string;
  evidence: { id: string; source: string; content: string; redacted: boolean }[];
  citations: { id: string; source: string }[];
  citation_valid: boolean;
  citation_errors: string[];
  degraded: string[];
  executed: boolean;
  pending_action_id: string | null;
  latency_ms: number;
  tokens: number;
  run_id: string;
};

export type PendingAction = {
  id: string;
  plan: string;
  status: "pending" | "approved" | "denied";
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
};

export type EvalRun = {
  id?: string;
  created_at?: string;
  accuracy?: number | null;
  refusal_rate?: number | null;
  avg_latency_ms?: number | null;
  avg_tokens?: number | null;
  payload?: Record<string, unknown>;
};

export const api = {
  chat: (question: string) =>
    request<ChatResponse>("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  chatWithFile: (question: string, file: File) => {
    const form = new FormData();
    form.append("question", question);
    form.append("file", file, file.name);
    return request<ChatResponse>("/api/v1/chat/upload", {
      method: "POST",
      body: form,
    });
  },

  pendingActions: () => request<PendingAction[]>("/api/v1/pending_actions"),

  decide: (id: string, status: "approved" | "denied", decidedBy: string) =>
    request<{ status: string; outcome?: string }>(`/api/v1/pending_actions/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ status, decided_by: decidedBy }),
    }),

  latestMetrics: () => request<EvalRun>("/api/v1/metrics/latest"),
  metricsHistory: (limit = 50) =>
    request<
      { created_at?: string; accuracy?: number | null; refusal_rate?: number | null }[]
    >(`/api/v1/metrics/history?limit=${limit}`),

  injectionAttempts: () =>
    request<{ total: number; blocked: number; rows: unknown[] }>(
      "/api/v1/injection_attempts?limit=50"
    ),
};
