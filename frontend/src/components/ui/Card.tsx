import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  bodyClassName?: string;
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  ...rest
}: CardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-bg-card/80 shadow-lg shadow-black/20 backdrop-blur",
        className,
      )}
      {...rest}
    >
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </div>
  );
}
