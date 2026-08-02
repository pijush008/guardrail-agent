"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export function TrendChart({
  data,
}: {
  data: {
    created_at?: string;
    accuracy?: number | null;
    refusal_rate?: number | null;
  }[];
}) {
  const rows = data.map((d, i) => ({
    name: `#${i + 1}`,
    accuracy: d.accuracy ?? null,
    refusal: d.refusal_rate ?? null,
  }));

  return (
    <div className="rounded-xl border border-ink-700 bg-ink-900 p-4">
      <h2 className="mb-2 text-sm font-semibold text-ink-300">
        Accuracy &amp; refusal rate across eval runs
      </h2>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
            <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} />
            <YAxis domain={[0, 100]} stroke="#94a3b8" fontSize={12} unit="%" />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 8,
              }}
              labelStyle={{ color: "#cbd5e1" }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="accuracy"
              name="Accuracy %"
              stroke="#38bdf8"
              strokeWidth={2}
              dot={{ r: 3 }}
            />
            <Line
              type="monotone"
              dataKey="refusal"
              name="Refusal %"
              stroke="#34d399"
              strokeWidth={2}
              dot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
