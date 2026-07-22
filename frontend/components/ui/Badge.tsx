import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type BadgeVariant = "default" | "success" | "warning" | "info" | "muted";

type BadgeProps = {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
};

const variantStyles: Record<BadgeVariant, string> = {
  default: "bg-zinc-800 text-zinc-300 border-zinc-700",
  success: "bg-emerald-950/60 text-emerald-400 border-emerald-900/60",
  warning: "bg-amber-950/60 text-amber-400 border-amber-900/60",
  info: "bg-blue-950/60 text-blue-400 border-blue-900/60",
  muted: "bg-zinc-900 text-zinc-500 border-zinc-800",
};

export function Badge({
  children,
  variant = "default",
  className,
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        variantStyles[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
