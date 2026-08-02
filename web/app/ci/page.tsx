"use client";

import { useEffect, useState } from "react";
import { api, type CiStatus } from "@/lib/api";

export default function CiPage() {
  const [ci, setCi] = useState<CiStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .ciStatus()
      .then(setCi)
      .catch((err) => setError((err as Error).message));
  }, []);

  const statusColor =
    ci?.integration === "github"
      ? ci.status === "success"
        ? "text-ok"
        : ci.status === "in_progress"
          ? "text-warn"
          : "text-bad"
      : "text-ink-400";

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-ink-200">CI status</h1>

      {error && (
        <div className="rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </div>
      )}

      {!ci && !error && (
        <div className="rounded-xl border border-ink-700 bg-ink-900 p-6 text-center text-sm text-ink-400">
          Loading…
        </div>
      )}

      {ci && ci.integration === "mock" && (
        <div className="rounded-xl border border-ink-700 bg-ink-900 p-6 text-sm text-ink-400">
          <div className="flex items-center gap-2">
            <span className={`text-lg ${statusColor}`}>●</span>
            <span className="font-mono text-ink-300">status: {ci.status}</span>
          </div>
          <p className="mt-2">{ci.message}</p>
          <p className="mt-3 text-xs text-ink-500">
            This page shows a live GitHub Actions status when the service runs
            inside CI (the <code className="text-ink-400">GITHUB_ACTIONS</code> env is
            set). Locally it reports an honest mock instead.
          </p>
        </div>
      )}

      {ci && ci.integration === "github" && (
        <div className="rounded-xl border border-ink-700 bg-ink-900 p-6">
          <div className="flex items-center gap-2">
            <span className={`text-lg ${statusColor}`}>●</span>
            <span className="font-mono text-ink-200">{ci.workflow}</span>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                ci.status === "success"
                  ? "bg-ok/15 text-ok"
                  : ci.status === "in_progress"
                    ? "bg-warn/15 text-warn"
                    : "bg-bad/15 text-bad"
              }`}
            >
              {ci.status}
            </span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-ink-400">Branch</dt>
              <dd className="font-mono text-ink-200">{ci.branch}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-400">Commit</dt>
              <dd className="font-mono text-ink-200">{ci.sha.slice(0, 7)}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-400">Run</dt>
              <dd className="font-mono text-ink-200">{ci.run_id}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-400">Eval gate</dt>
              <dd className="text-ink-200">≥80% pass-rate on all categories</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
