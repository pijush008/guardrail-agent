"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase, SUPABASE_CONFIGURED } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const sb = getSupabase();
    if (!sb) {
      // No Supabase configured → demo mode auto-authenticates.
      router.push("/approvals");
      return;
    }
    const { error } = await sb.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) {
      setMsg(error.message);
      return;
    }
    router.push("/approvals");
  }

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <div className="rounded-2xl border border-ink-700 bg-ink-900 p-6">
        <h1 className="text-xl font-bold text-ink-200">Approver sign in</h1>
        <p className="mt-1 text-sm text-ink-400">
          Only authenticated approvers can approve or deny high-stakes actions.
        </p>
        <form onSubmit={signIn} className="mt-5 space-y-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="approver@corp.example"
            className="w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-200 placeholder:text-ink-500 focus:border-accent focus:outline-none"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-200 placeholder:text-ink-500 focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-accent py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        {msg && <div className="mt-3 text-sm text-bad">{msg}</div>}
        {!SUPABASE_CONFIGURED && (
          <div className="mt-4 rounded-lg border border-warn/40 bg-warn/10 p-3 text-xs text-warn">
            Supabase not configured — running in demo mode. Set
            NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY to enforce
            real auth.
          </div>
        )}
      </div>
    </div>
  );
}
