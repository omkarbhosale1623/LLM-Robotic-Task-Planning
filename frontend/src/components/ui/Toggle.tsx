import { cn } from "@/lib/utils";

interface ToggleOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

interface ToggleProps<T extends string> {
  options: ToggleOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** A segmented control / pill toggle used for the planner-mode and scene picker. */
export function Toggle<T extends string>({
  options,
  value,
  onChange,
  className,
}: ToggleProps<T>) {
  return (
    <div
      className={cn(
        "inline-flex rounded-lg border border-line bg-bg-soft p-0.5 text-xs",
        className,
      )}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          disabled={opt.disabled}
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded-md px-2.5 py-1 font-medium transition-colors",
            value === opt.value
              ? "bg-accent text-slate-950"
              : "text-slate-300 hover:text-white",
            opt.disabled && "cursor-not-allowed opacity-40",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
