import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Conditional className builder with Tailwind conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Map a named object/CSS color to a concrete hex for the scene renderer. */
export const COLOR_HEX: Record<string, string> = {
  red: "#ef4444",
  blue: "#3b82f6",
  green: "#22c55e",
  yellow: "#eab308",
  orange: "#f97316",
  purple: "#a855f7",
  black: "#0f172a",
  white: "#e2e8f0",
};

export function colorHex(color: string): string {
  return COLOR_HEX[color.toLowerCase()] ?? "#94a3b8";
}

/** Format a 0..1 rate as a percentage string. */
export function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
