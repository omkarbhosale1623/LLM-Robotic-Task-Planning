"use client";

import {
  ArrowDown,
  Check,
  CircleDot,
  Hand,
  MoveRight,
  PackageOpen,
  Scan,
  Timer,
  X,
} from "lucide-react";
import type { ReactNode } from "react";

import type { Plan, StepEvent } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

interface PlanVisualiserProps {
  plan: Plan | null;
  events?: StepEvent[];
  activeIndex?: number;
}

const ACTION_ICON: Record<string, ReactNode> = {
  move_to: <MoveRight className="h-4 w-4" />,
  pick: <Hand className="h-4 w-4" />,
  place: <PackageOpen className="h-4 w-4" />,
  open_gripper: <CircleDot className="h-4 w-4" />,
  close_gripper: <CircleDot className="h-4 w-4" />,
  detect: <Scan className="h-4 w-4" />,
  wait: <Timer className="h-4 w-4" />,
};

type StepStatus = "pending" | "active" | "done" | "failed";

function statusFor(
  index: number,
  events: StepEvent[],
  activeIndex: number,
): StepStatus {
  const event = events.find((e) => e.index === index);
  if (event) return event.success ? "done" : "failed";
  if (index === activeIndex) return "active";
  return "pending";
}

/**
 * Renders the decomposed action sequence as a status-aware, ordered mini-DAG:
 * each primitive is a node with its args and rationale, connected top-to-bottom,
 * and colored by execution status (pending / active / done / failed).
 */
export function PlanVisualiser({ plan, events = [], activeIndex = -1 }: PlanVisualiserProps) {
  if (!plan || plan.steps.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-slate-500">
        No plan yet. Enter an instruction to decompose it into primitives.
      </div>
    );
  }

  return (
    <ol className="space-y-0">
      {plan.steps.map((step, index) => {
        const status = statusFor(index, events, activeIndex);
        const event = events.find((e) => e.index === index);
        const target = step.args?.target as string | undefined;

        return (
          <li key={index}>
            <div
              className={cn(
                "flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors",
                status === "active" && "border-accent bg-accent/5",
                status === "done" && "border-ok/30 bg-ok/5",
                status === "failed" && "border-bad/40 bg-bad/5",
                status === "pending" && "border-line bg-bg-soft/50",
              )}
            >
              <div
                className={cn(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                  status === "active" && "bg-accent text-slate-950",
                  status === "done" && "bg-ok/20 text-ok",
                  status === "failed" && "bg-bad/20 text-bad",
                  status === "pending" && "bg-bg-card text-slate-400",
                )}
              >
                {status === "done" ? (
                  <Check className="h-4 w-4" />
                ) : status === "failed" ? (
                  <X className="h-4 w-4" />
                ) : (
                  (ACTION_ICON[step.action] ?? <CircleDot className="h-4 w-4" />)
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-semibold text-slate-100">
                    {step.action}
                  </span>
                  {target && (
                    <Badge tone="accent" className="font-mono">
                      {target}
                    </Badge>
                  )}
                  {step.args?.seconds != null && (
                    <Badge tone="neutral">{String(step.args.seconds)}s</Badge>
                  )}
                  <span className="ml-auto text-[11px] text-slate-500">#{index + 1}</span>
                </div>
                {step.rationale && (
                  <p className="mt-0.5 text-xs text-slate-400">{step.rationale}</p>
                )}
                {event && !event.success && (
                  <p className="mt-1 text-xs text-bad">precondition failed: {event.reason}</p>
                )}
              </div>
            </div>

            {index < plan.steps.length - 1 && (
              <div className="flex justify-start pl-[1.35rem]">
                <ArrowDown className="my-0.5 h-3.5 w-3.5 text-slate-600" />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
