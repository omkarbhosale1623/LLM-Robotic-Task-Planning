import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Tone = "neutral" | "ok" | "warn" | "bad" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "border-line bg-bg-soft text-slate-300",
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-warn/40 bg-warn/10 text-warn",
  bad: "border-bad/40 bg-bad/10 text-bad",
  accent: "border-accent/40 bg-accent/10 text-accent",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
