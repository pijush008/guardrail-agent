"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getSupabase, SUPABASE_CONFIGURED } from "./supabase";

type Session = {
  user?: { id?: string; email?: string } | null;
  loading: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<Session>({
  user: null,
  loading: true,
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<{ id?: string; email?: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sb = getSupabase();
    if (!sb) {
      // No Supabase configured: run in "demo authenticated" mode so the UI
      // is usable offline. In production set the env vars to enforce auth.
      setUser({ id: "demo-user", email: "demo@guardrail.local" });
      setLoading(false);
      return;
    }
    sb.auth.getSession().then(({ data }) => {
      setUser(data.session?.user ?? null);
      setLoading(false);
    });
    const { data: sub } = sb.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  async function signOut() {
    const sb = getSupabase();
    if (sb) await sb.auth.signOut();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export { SUPABASE_CONFIGURED };
