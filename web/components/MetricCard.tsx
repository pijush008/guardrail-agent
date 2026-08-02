export function MetricCard({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad" | "warn" | "neutral";
}) {
  const color =
    tone === "good"
      ? "text-ok"
      : tone === "bad"
        ? "text-bad"
        : tone === "warn"
          ? "text-warn"
          : "text-accent";
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-900 p-4">
      <div className="text-[11px] uppercase tracking-wider text-ink-400">
        {label}
      </div>
      <div className={`mt-1 text-3xl font-bold ${color}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-400">{sub}</div>}
    </div>
  );
}
