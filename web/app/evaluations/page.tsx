"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type EvalCase, type EvalRun } from "@/lib/api";

export default function EvaluationsPage() {
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    (async () => {
      try {
        const [c, r] = await Promise.all([api.evalCases(), api.evalRuns(25)]);
        setCases(c);
        setRuns(r);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  const byCategory = useMemo(() => {
    const map = new Map<string, { total: number; attack: number }>();
    for (const c of cases) {
      const e = map.get(c.category) ?? { total: 0, attack: 0 };
      e.total += 1;
      if (c.attack) e.attack += 1;
      map.set(c.category, e);
    }
    return [...map.entries()];
  }, [cases]);

  const filtered = useMemo(
    () => (filter ? cases.filter((c) => c.category === filter) : cases),
    [cases, filter]
  );

  async function runSuite() {
    setRunning(true);
    setError(null);
    try {
      const out = await api.runEvaluations(
        filter ? { category: filter } : { limit: 145 }
      );
      const summary = out.summary as Record<string, unknown>;
      const accuracy = summary.accuracy;
      setRuns((prev) => [
        {
          created_at: new Date().toISOString(),
          accuracy: typeof accuracy === "number" ? accuracy : null,
          refusal_rate:
            typeof summary.refusal_rate === "number"
              ? (summary.refusal_rate as number)
              : null,
        },
        ...prev,
      ]);
    } catch (err) {
      setError(
        `${(err as Error).message} — start the Python service (uvicorn service.main:app) and add an LLM API key to run the real suite.`
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink-200">Evaluations</h1>
          <p className="mt-1 text-sm text-ink-400">
            {cases.length} curated cases across adversarial, edge, failure and
            permission categories — run them as a pass/fail gate.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-200"
          >
            <option value="">All categories</option>
            {byCategory.map(([cat]) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
          <button
            disabled={running}
            onClick={runSuite}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
          >
            {running ? "Running…" : "Run suite"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {byCategory.map(([cat, { total, attack }]) => (
          <button
            key={cat}
            onClick={() => setFilter(filter === cat ? "" : cat)}
            className={`rounded-xl border p-4 text-left transition ${
              filter === cat
                ? "border-accent bg-ink-900"
                : "border-ink-700 bg-ink-900 hover:border-ink-600"
            }`}
          >
            <div className="text-[11px] uppercase tracking-wider text-ink-400">
              {cat}
            </div>
            <div className="mt-1 text-2xl font-bold text-ink-200">{total}</div>
            <div className="text-xs text-ink-400">
              {attack} adversarial / {total - attack} benign
            </div>
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-ink-700 bg-ink-900">
        <div className="border-b border-ink-700 px-4 py-3 text-sm font-semibold text-ink-200">
          Cases ({filtered.length})
        </div>
        <div className="max-h-96 divide-y divide-ink-700/60 overflow-y-auto">
          {filtered.map((c) => (
            <div key={c.id} className="flex items-start gap-3 px-4 py-2.5 text-sm">
              <span
                className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                  c.attack ? "bg-bad" : "bg-ok"
                }`}
                title={c.attack ? "attack" : "benign"}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-ink-300">{c.input}</div>
                <div className="text-xs text-ink-400">
                  {c.expect_block ? "expect block" : "expect answer"} ·{" "}
                  {c.require_json ? "JSON output" : "free-form"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {runs.length > 0 && (
        <div className="rounded-xl border border-ink-700 bg-ink-900">
          <div className="border-b border-ink-700 px-4 py-3 text-sm font-semibold text-ink-200">
            Recent runs
          </div>
          <div className="divide-y divide-ink-700/60">
            {runs.map((r, i) => (
              <div key={r.id ?? i} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <span className="text-xs text-ink-400">
                  {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                </span>
                <span className="font-mono text-ink-300">
                  {r.accuracy != null ? `${r.accuracy}%` : "—"} acc
                </span>
                <span className="font-mono text-ink-300">
                  {r.refusal_rate != null ? `${r.refusal_rate}%` : "—"} refusal
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
