"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/", label: "Chat" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/evaluations", label: "Evaluations" },
  { href: "/guardrails", label: "Guardrails" },
  { href: "/approvals", label: "Approvals" },
  { href: "/runs", label: "Runs" },
  { href: "/ci", label: "CI" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const { user, signOut } = useAuth();

  return (
    <header className="sticky top-0 z-20 border-b border-ink-700 bg-ink-900/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-black text-ink-950">
            GA
          </span>
          <span className="font-semibold text-ink-200">
            Guardrail Agent
          </span>
        </Link>
        <nav className="flex flex-1 gap-1 text-sm">
          {LINKS.map((l) => {
            const active =
              pathname === l.href ||
              (l.href !== "/" && pathname.startsWith(l.href));
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-lg px-3 py-1.5 transition ${
                  active
                    ? "bg-ink-800 text-ink-200"
                    : "text-ink-400 hover:bg-ink-800 hover:text-ink-200"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        {user && (
          <div className="flex items-center gap-3 text-xs text-ink-400">
            <span className="hidden sm:inline">{user.email ?? user.id}</span>
            <button
              onClick={() => signOut()}
              className="rounded-lg border border-ink-700 px-2.5 py-1 hover:bg-ink-800"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
