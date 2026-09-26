"use client";

import { CheckCircle2, XCircle } from "lucide-react";

import type { StepEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A horizontal timeline of executed steps with per-step success markers. */
export function ExecutionTimeline({
  events,
  activeIndex,
}: {
  events: StepEvent[];
  activeIndex: number;
}) {
  if (events.length === 0 && activeIndex < 0) {
    return (
      <div className="py-4 text-center text-xs text-slate-500">
        Execution events will appear here as the plan runs.
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {events.map((e) => {
        const target = e.args?.target as string | undefined;
        return (
        <div
          key={e.index}
          title={`${e.action}${target ? ` ${target}` : ""} — ${e.reason}`}
          className={cn(
            "flex items-center gap-1 rounded-md border px-2 py-1 text-xs",
            e.success
              ? "border-ok/30 bg-ok/5 text-ok"
              : "border-bad/40 bg-bad/5 text-bad",
            e.index === activeIndex && "ring-2 ring-accent/60",
          )}
        >
          {e.success ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <XCircle className="h-3.5 w-3.5" />
          )}
          <span className="font-mono">{e.action}</span>
        </div>
        );
      })}
    </div>
  );
}
