import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-slate-950 hover:bg-accent-soft disabled:bg-slate-700 disabled:text-slate-400",
  secondary:
    "border border-line bg-bg-soft text-slate-200 hover:border-accent/60 hover:text-white disabled:opacity-50",
  ghost: "text-slate-300 hover:bg-bg-soft hover:text-white disabled:opacity-50",
};

export function Button({ variant = "primary", className, ...rest }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-accent/50 disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}
