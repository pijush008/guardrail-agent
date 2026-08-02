"use client";

import { useEffect, useState } from "react";
import { api, type AgentRun, type AgentRunDetail } from "@/lib/api";

export default function RunsPage() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selected, setSelected] = useState<AgentRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .agentRuns(50)
      .then(setRuns)
      .catch((err) => setError((err as Error).message));
  }, []);

  async function open(runId: string) {
    setError(null);
    try {
      setSelected(await api.agentRunDetail(runId));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-2">
      <div className="rounded-xl border border-ink-700 bg-ink-900">
        <div className="border-b border-ink-700 px-4 py-3 text-sm font-semibold text-ink-200">
          Agent runs
        </div>
        <div className="max-h-[32rem] divide-y divide-ink-700/60 overflow-y-auto">
          {runs.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-ink-400">
              No agent runs yet — ask the agent something in the Chat tab.
            </div>
          )}
          {runs.map((r) => (
            <button
              key={r.run_id}
              onClick={() => open(r.run_id)}
              className={`block w-full px-4 py-3 text-left transition hover:bg-ink-800/60 ${
                selected?.run_id === r.run_id ? "bg-ink-800/60" : ""
              }`}
            >
              <div className="truncate text-sm text-ink-300">{r.question}</div>
              <div className="mt-1 flex items-center justify-between text-xs text-ink-400">
                <span>{r.created_at ? new Date(r.created_at).toLocaleString() : ""}</span>
                <span>
                  {r.citations?.length ?? 0} citations · {r.evidence_count ?? 0} evidence
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-ink-700 bg-ink-900">
        <div className="border-b border-ink-700 px-4 py-3 text-sm font-semibold text-ink-200">
          {selected ? "Trace" : "Run detail"}
        </div>
        {!selected ? (
          <div className="px-4 py-8 text-center text-sm text-ink-400">
            Select a run to see its 13-stage pipeline trace, citations and evidence.
          </div>
        ) : (
          <div className="max-h-[32rem] overflow-y-auto p-4">
            <div className="text-sm text-ink-300">{selected.answer}</div>

            {selected.trace && selected.trace.length > 0 && (
              <div className="mt-4 space-y-1">
                {selected.trace.map((s, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 rounded-lg bg-ink-800/40 px-3 py-1.5 text-xs"
                  >
                    <span className="font-mono text-ink-500">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        s.status === "ok"
                          ? "bg-ok/15 text-ok"
                          : s.status === "skip" || s.status === "na"
                            ? "bg-ink-700 text-ink-400"
                            : "bg-warn/15 text-warn"
                      }`}
                    >
                      {s.status}
                    </span>
                    <span className="font-mono text-ink-300">{s.step}</span>
                  </div>
                ))}
              </div>
            )}

            {selected.evidence && selected.evidence.length > 0 && (
              <div className="mt-4">
                <div className="text-[11px] uppercase tracking-wider text-ink-400">
                  Evidence
                </div>
                {selected.evidence.map((ev) => (
                  <div
                    key={ev.id}
                    className="mt-2 rounded-lg border border-ink-700/60 bg-ink-800/40 p-3 text-xs text-ink-400"
                  >
                    <span className="font-mono text-accent">{ev.source}</span>
                    {ev.content_redacted && (
                      <div className="mt-1">{ev.content_redacted}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad lg:col-span-2">
          {error}
        </div>
      )}
    </div>
  );
}
