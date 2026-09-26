"use client";

import { CornerDownLeft, Bot, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

export interface ConsoleEntry {
  id: string;
  role: "user" | "agent";
  text: string;
  tone?: "ok" | "bad" | "neutral";
  meta?: string;
}

interface InstructionConsoleProps {
  history: ConsoleEntry[];
  onSubmit: (instruction: string) => void;
  disabled?: boolean;
  suggestions?: string[];
}

/** Chat-style instruction console: input + scrollable history of turns. */
export function InstructionConsole({
  history,
  onSubmit,
  disabled,
  suggestions = [],
}: InstructionConsoleProps) {
  const [value, setValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [history.length]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
        {history.length === 0 && (
          <div className="rounded-lg border border-dashed border-line p-4 text-sm text-slate-400">
            Give the robot a natural-language instruction, e.g.{" "}
            <span className="font-mono text-slate-200">
              &quot;pick up the red block and place it on the shelf&quot;
            </span>
            .
          </div>
        )}
        {history.map((entry) => (
          <div
            key={entry.id}
            className={cn(
              "flex gap-2.5 animate-fade-in",
              entry.role === "user" ? "flex-row-reverse" : "flex-row",
            )}
          >
            <div
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                entry.role === "user" ? "bg-accent/20 text-accent" : "bg-bg-soft text-slate-300",
              )}
            >
              {entry.role === "user" ? (
                <User className="h-4 w-4" />
              ) : (
                <Bot className="h-4 w-4" />
              )}
            </div>
            <div
              className={cn(
                "max-w-[85%] rounded-xl px-3 py-2 text-sm",
                entry.role === "user"
                  ? "bg-accent/15 text-slate-100"
                  : "border border-line bg-bg-soft text-slate-200",
              )}
            >
              <p>{entry.text}</p>
              {entry.meta && (
                <div className="mt-1.5 flex items-center gap-2">
                  <Badge tone={entry.tone ?? "neutral"}>{entry.meta}</Badge>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {suggestions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              disabled={disabled}
              onClick={() => setValue(s)}
              className="rounded-full border border-line bg-bg-soft px-2.5 py-1 text-xs text-slate-400 transition-colors hover:border-accent/50 hover:text-slate-200 disabled:opacity-40"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 flex items-end gap-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder="Instruct the robot…"
          disabled={disabled}
          className="flex-1 resize-none rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:outline-none disabled:opacity-50"
        />
        <Button onClick={submit} disabled={disabled || !value.trim()} className="h-[42px]">
          <CornerDownLeft className="h-4 w-4" />
          Run
        </Button>
      </div>
    </div>
  );
}
