"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type PendingAction } from "@/lib/api";
import { getSupabase, SUPABASE_CONFIGURED } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";

function parsePlan(plan: string): { plan?: unknown[]; tool?: string; action?: string } {
  try {
    const data = JSON.parse(plan);
    if (typeof data === "object" && data !== null) return data;
  } catch {
    /* fall through */
  }
  return { plan: [] };
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: "bg-warn/15 text-warn",
    approved: "bg-ok/15 text-ok",
    denied: "bg-bad/15 text-bad",
  };
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${map[status] || ""}`}>
      {status}
    </span>
  );
}

export default function ApprovalsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [rows, setRows] = useState<PendingAction[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Gate: only authenticated approvers may approve/deny.
  useEffect(() => {
    if (authLoading) return;
    if (!user) router.push("/login");
  }, [user, authLoading, router]);

  useEffect(() => {
    let disposed = false;

    async function refresh() {
      try {
        const list = await api.pendingActions();
        if (!disposed) setRows(list);
      } catch (err) {
        if (!disposed) setError((err as Error).message);
      }
    }

    refresh();

    const sb = getSupabase();
    if (sb) {
      // Realtime: Supabase pushes new/updated rows to us instantly.
      const channel = sb
        .channel("pending-actions")
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table: "pending_actions" },
          () => refresh()
        )
        .subscribe();
      return () => {
        disposed = true;
        sb.removeChannel(channel);
      };
    }
    // Fallback when Supabase is not configured: poll the service.
    const interval = setInterval(refresh, 5000);
    return () => {
      disposed = true;
      clearInterval(interval);
    };
  }, []);

  async function decide(action: PendingAction, status: "approved" | "denied") {
    setBusyId(action.id);
    setError(null);
    try {
      const out = await api.decide(action.id, status, user?.email ?? user?.id ?? "unknown");
      if (out.status === "approved" && out.outcome) {
        // surface the executed-action outcome in the row
      }
      const list = await api.pendingActions();
      setRows(list);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-bold text-ink-200">Approvals</h1>
      <p className="mt-1 text-sm text-ink-400">
        High-stakes actions proposed by the agent never execute until an
        approver approves them here
        {SUPABASE_CONFIGURED ? " — updates arrive in realtime" : " (polling mode)"}.
      </p>

      {error && (
        <div className="mt-4 rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {rows.length === 0 && (
          <div className="rounded-xl border border-ink-700 bg-ink-900 p-6 text-center text-sm text-ink-400">
            No pending actions. Ask the agent to do something high-stakes —
            e.g. “Send a reminder email to finance” — to see it appear here.
          </div>
        )}
        {rows.map((r) => {
          const plan = parsePlan(r.plan);
          const steps = (plan.plan as Array<{ action?: string; subject?: string; rationale?: string }>) || [];
          return (
            <div
              key={r.id}
              className="rounded-xl border border-ink-700 bg-ink-900 p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-ink-400">
                  {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                  {r.decided_by ? ` · decided by ${r.decided_by}` : ""}
                </div>
                <StatusPill status={r.status} />
              </div>

              {steps.map((s, i) => (
                <div
                  key={i}
                  className="mt-3 rounded-lg border border-ink-700/60 bg-ink-800/50 p-3"
                >
                  <div className="font-mono text-sm text-accent">
                    {s.action || "action"} → {s.subject}
                  </div>
                  {s.rationale && (
                    <div className="mt-1 text-xs text-ink-400">{s.rationale}</div>
                  )}
                </div>
              ))}

              {r.status === "pending" && (
                <div className="mt-4 flex gap-2">
                  <button
                    disabled={busyId === r.id}
                    onClick={() => decide(r, "approved")}
                    className="rounded-lg bg-ok px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
                  >
                    Approve &amp; execute
                  </button>
                  <button
                    disabled={busyId === r.id}
                    onClick={() => decide(r, "denied")}
                    className="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-300 hover:bg-ink-800 disabled:opacity-50"
                  >
                    Deny
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
