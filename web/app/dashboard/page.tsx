"use client";

import { useEffect, useState } from "react";
import { api, type EvalRun } from "@/lib/api";
import { MetricCard } from "@/components/MetricCard";
import { TrendChart } from "@/components/TrendChart";

type History = {
  created_at?: string;
  accuracy?: number | null;
  refusal_rate?: number | null;
}[];

export default function DashboardPage() {
  const [latest, setLatest] = useState<EvalRun | null>(null);
  const [history, setHistory] = useState<History>([]);
  const [blocked, setBlocked] = useState<{ total: number; blocked: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [l, h, ia] = await Promise.all([
          api.latestMetrics(),
          api.metricsHistory(50),
          api.injectionAttempts().catch(() => null),
        ]);
        setLatest(l);
        setHistory(h);
        if (ia) setBlocked({ total: ia.total, blocked: ia.blocked });
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="text-sm text-ink-400">Loading latest eval metrics…</div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-bad/40 bg-bad/10 p-4 text-sm text-bad">
        Could not load metrics: {error}. Start the Python service
        (<code className="text-ink-300">uvicorn service.main:app</code>) and run the
        eval suite (<code className="text-ink-300">python -m evals.eval_runner</code>).
      </div>
    );
  }

  if (!latest) {
    return (
      <div className="rounded-xl border border-ink-700 bg-ink-900 p-4 text-sm text-ink-400">
        No eval runs recorded yet. Run{" "}
        <code className="text-ink-300">python -m evals.eval_runner --outdir reports</code>{" "}
        to populate the dashboard.
      </div>
    );
  }

  const refusal = latest.refusal_rate;
  const lat = latest.avg_latency_ms;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-200">Metrics dashboard</h1>
        <p className="mt-1 text-sm text-ink-400">
          Latest eval run{" "}
          {latest.created_at
            ? `· ${new Date(latest.created_at).toLocaleString()}`
            : ""}
          {blocked
            ? ` · guardrail blocked ${blocked.blocked}/${blocked.total} recorded attempts`
            : ""}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Accuracy"
          value={latest.accuracy != null ? `${latest.accuracy}%` : "—"}
          sub="pass rate across all categories"
          tone={latest.accuracy != null && latest.accuracy >= 80 ? "good" : "warn"}
        />
        <MetricCard
          label="Refusal rate"
          value={refusal != null ? `${refusal}%` : "—"}
          sub="adversarial prompts blocked"
          tone={refusal != null && refusal >= 90 ? "good" : "warn"}
        />
        <MetricCard
          label="Latency"
          value={lat != null ? `${lat}ms` : "—"}
          sub="avg per task"
        />
        <MetricCard
          label="Token usage"
          value={latest.avg_tokens != null ? `${latest.avg_tokens}` : "—"}
          sub="avg tokens per task"
        />
      </div>

      {history.length > 0 && <TrendChart data={history} />}
    </div>
  );
}
