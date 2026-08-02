"use client";

import { useEffect, useState } from "react";
import { api, type MetricsAggregate } from "@/lib/api";

export default function SettingsPage() {
  const [metrics, setMetrics] = useState<MetricsAggregate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .metricsAggregate()
      .then(setMetrics)
      .catch((err) => setError((err as Error).message));
  }, []);

  const latest = metrics?.latest;

  const rows: { k: string; v: string }[] = [];
  if (latest) {
    if (latest.accuracy != null)
      rows.push({ k: "Eval pass rate", v: `${latest.accuracy}%` });
    if (latest.refusal_rate != null)
      rows.push({ k: "Refusal rate", v: `${latest.refusal_rate}%` });
    if (latest.avg_latency_ms != null)
      rows.push({ k: "Avg latency", v: `${latest.avg_latency_ms}ms` });
    if (latest.avg_tokens != null)
      rows.push({ k: "Avg tokens", v: `${latest.avg_tokens}` });
  }
  const inj = metrics?.guardrails?.injection_attempts;
  if (inj != null) rows.push({ k: "Injection attempts recorded", v: `${inj}` });
  const pend = metrics?.approvals?.pending;
  if (pend != null) rows.push({ k: "Pending approvals", v: `${pend}` });

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-ink-200">Settings</h1>

      {error && (
        <div className="rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </div>
      )}

      <section className="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <h2 className="text-sm font-semibold text-ink-200">Runtime overview</h2>
        <div className="mt-3 divide-y divide-ink-700/60">
          {rows.length === 0 && (
            <div className="text-sm text-ink-400">
              No metrics recorded yet. Run the eval suite to populate this page.
            </div>
          )}
          {rows.map((r) => (
            <div key={r.k} className="flex items-center justify-between py-2 text-sm">
              <span className="text-ink-400">{r.k}</span>
              <span className="font-mono text-ink-200">{r.v}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <h2 className="text-sm font-semibold text-ink-200">Backend configuration</h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-ink-400">LLM provider</dt>
            <dd className="font-mono text-ink-200">
              Groq / OpenAI via <code>GROQ_API_KEY</code> or <code>OPENAI_API_KEY</code>
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-400">Offline eval mode</dt>
            <dd className="font-mono text-ink-200">
              <code>GUARDRAIL_FAKE_LLM=1</code>
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-400">Store</dt>
            <dd className="font-mono text-ink-200">Supabase or local JSON</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-400">Approval gate</dt>
            <dd className="font-mono text-ink-200">
              High-stakes actions wait for manual approval
            </dd>
          </div>
        </dl>
      </section>

      <section className="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <h2 className="text-sm font-semibold text-ink-200">Next steps</h2>
        <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-ink-400">
          <li>
            Add an LLM API key to GitHub Secrets to make CI enforce the 80% pass-rate
            gate.
          </li>
          <li>
            Wire <code>NEXT_PUBLIC_SUPABASE_URL</code> /{" "}
            <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> for realtime approvals.
          </li>
          <li>
            Point <code>PYTHON_SERVICE_URL</code> at your deployed FastAPI service.
          </li>
        </ul>
      </section>
    </div>
  );
}
