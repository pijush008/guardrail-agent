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

export type EvalCase = {
  id: string;
  category: string;
  input: string;
  pass: string[];
  attack: boolean;
  expect_block: boolean;
  approval_mode?: string;
  require_json: boolean;
};

export type AgentRun = {
  run_id: string;
  question: string;
  answer: string;
  citations: { id: string; source: string }[];
  evidence_count: number;
  sources: string[];
  created_at: string;
};

export type AgentRunDetail = AgentRun & {
  evidence: { id: string; source: string; content_redacted?: string }[];
  trace: { step: string; status: string; detail?: unknown }[];
};

export type GuardrailEvents = {
  total: number;
  blocked: number;
  types: string[];
  events: { id?: string; input?: string; blocked?: boolean; created_at?: string }[];
};

export type CiStatus =
  | {
      integration: "github";
      workflow: string;
      branch: string;
      sha: string;
      run_id: string;
      status: string;
    }
  | { integration: "mock"; message: string; status: string };

export type MetricsAggregate = {
  latest?: EvalRun | null;
  history?: EvalRun[];
  totals?: Record<string, unknown>;
  guardrails?: { injection_attempts?: number; injection_blocked?: number };
  approvals?: { pending?: number };
};

export const api = {
  chat: (question: string) =>
    request<ChatResponse>("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  agentRun: (question: string) =>
    request<ChatResponse & { status?: string }>("/api/v1/agent/run", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  agentRuns: (limit = 50) => request<AgentRun[]>(`/api/v1/agent/runs?limit=${limit}`),

  agentRunDetail: (runId: string) =>
    request<AgentRunDetail>(`/api/v1/agent/runs/${runId}`),

  evalCases: () => request<EvalCase[]>("/api/v1/evaluations/cases"),

  runEvaluations: (params?: { category?: string; limit?: number; min_pass?: number }) => {
    const q = new URLSearchParams();
    if (params?.category) q.set("category", params.category);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.min_pass) q.set("min_pass", String(params.min_pass));
    const qs = q.toString();
    return request<{ gate_passed: boolean; exit_code: number; summary: Record<string, unknown> }>(
      `/api/v1/evaluations/run${qs ? `?${qs}` : ""}`,
      { method: "POST", body: JSON.stringify({}) }
    );
  },

  evalRuns: (limit = 50) => request<EvalRun[]>(`/api/v1/evaluations/runs?limit=${limit}`),

  evalRunDetail: (id: string) => request<EvalRun & { cases?: unknown[] }>(`/api/v1/evaluations/runs/${id}`),

  guardrailEvents: (limit = 50) =>
    request<GuardrailEvents>(`/api/v1/guardrails/events?limit=${limit}`),

  metricsAggregate: () => request<MetricsAggregate>("/api/v1/metrics"),

  ciStatus: () => request<CiStatus>("/api/v1/ci/status"),

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
