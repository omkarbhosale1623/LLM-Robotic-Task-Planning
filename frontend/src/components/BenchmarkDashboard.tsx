"use client";

import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Stat } from "@/components/ui/Stat";
import { api } from "@/lib/api";
import type { BenchmarkReport, PlannerMode } from "@/lib/types";
import { cn, pct } from "@/lib/utils";

interface BenchmarkDashboardProps {
  mode: PlannerMode;
}

/** Circular completion-rate gauge built with an SVG arc. */
function Gauge({ rate }: { rate: number }) {
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * rate;
  const color = rate >= 0.85 ? "#22c55e" : rate >= 0.6 ? "#f59e0b" : "#ef4444";
  return (
    <div className="relative flex h-32 w-32 items-center justify-center">
      <svg viewBox="0 0 140 140" className="h-32 w-32 -rotate-90">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="#1f2937" strokeWidth="12" />
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute text-center">
        <div className="text-2xl font-bold text-slate-100">{pct(rate)}</div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500">completion</div>
      </div>
    </div>
  );
}

export function BenchmarkDashboard({ mode }: BenchmarkDashboardProps) {
  const { mutate, data, isPending, error } = useMutation<BenchmarkReport, Error, PlannerMode>({
    mutationFn: (m) => api.benchmark(m),
  });

  const chartData =
    data?.results.map((r) => ({
      id: `#${r.id}`,
      steps: r.step_count,
      passed: r.passed ? 1 : 0,
    })) ?? [];

  return (
    <Card
      title="Benchmark dashboard"
      subtitle="A fixed suite of 20 natural-language commands across 3 scenes."
      actions={
        <Button onClick={() => mutate(mode)} disabled={isPending}>
          {isPending ? <Spinner /> : <Play className="h-4 w-4" />}
          Run suite ({mode})
        </Button>
      }
    >
      {error && (
        <div className="mb-3 rounded-lg border border-bad/40 bg-bad/5 px-3 py-2 text-sm text-bad">
          {error.message}
        </div>
      )}

      {!data && !isPending && (
        <div className="py-10 text-center text-sm text-slate-500">
          Run the suite to compute the overall task-completion rate and per-command breakdown.
        </div>
      )}

      {isPending && (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-400">
          <Spinner /> Running 20 commands…
        </div>
      )}

      {data && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 items-center gap-4 sm:grid-cols-[auto,1fr]">
            <div className="flex justify-center">
              <Gauge rate={data.completion_rate} />
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Passed" value={`${data.passed}/${data.total}`} />
              <Stat label="Rate" value={pct(data.completion_rate)} />
              <Stat label="Mode" value={data.mode} />
              <Stat
                label="Failed"
                value={data.total - data.passed}
                hint={data.total - data.passed === 0 ? "all passing" : undefined}
              />
            </div>
          </div>

          {/* Success / fail grid */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Per-command grid
            </h3>
            <div className="grid grid-cols-5 gap-2 sm:grid-cols-10">
              {data.results.map((r) => (
                <div
                  key={r.id}
                  title={`${r.instruction} — ${r.passed ? "passed" : r.detail}`}
                  className={cn(
                    "flex aspect-square items-center justify-center rounded-md border text-xs font-semibold",
                    r.passed
                      ? "border-ok/40 bg-ok/15 text-ok"
                      : "border-bad/40 bg-bad/15 text-bad",
                  )}
                >
                  {r.id}
                </div>
              ))}
            </div>
          </div>

          {/* Steps-per-command bar */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Plan length per command (green = passed)
            </h3>
            <div className="h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
                  <XAxis dataKey="id" tick={{ fill: "#64748b", fontSize: 10 }} interval={0} />
                  <YAxis tick={{ fill: "#64748b", fontSize: 10 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      background: "#151c2c",
                      border: "1px solid #1f2937",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    labelStyle={{ color: "#e2e8f0" }}
                  />
                  <Bar dataKey="steps" radius={[3, 3, 0, 0]}>
                    {chartData.map((entry, i) => (
                      <Cell key={i} fill={entry.passed ? "#22c55e" : "#ef4444"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Breakdown table */}
          <div className="max-h-72 overflow-y-auto rounded-lg border border-line">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-bg-soft text-slate-400">
                <tr>
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">Instruction</th>
                  <th className="px-3 py-2">Scene</th>
                  <th className="px-3 py-2">Steps</th>
                  <th className="px-3 py-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.id} className="border-t border-line/60">
                    <td className="px-3 py-2 text-slate-500">{r.id}</td>
                    <td className="px-3 py-2 text-slate-200">{r.instruction}</td>
                    <td className="px-3 py-2 text-slate-400">{r.scene}</td>
                    <td className="px-3 py-2 text-slate-400">{r.step_count}</td>
                    <td className="px-3 py-2">
                      {r.passed ? (
                        <Badge tone="ok">pass</Badge>
                      ) : (
                        <Badge tone="bad">fail</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
