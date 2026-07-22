import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

type StatCardProps = {
  label: string;
  value: string;
  change?: string;
  changePositive?: boolean;
  icon: LucideIcon;
};

export function StatCard({
  label,
  value,
  change,
  changePositive = true,
  icon: Icon,
}: StatCardProps) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 p-5">
      <div className="flex items-start justify-between">
        <div className="space-y-3">
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            {label}
          </p>
          <p className="text-2xl font-semibold tracking-tight text-zinc-50">
            {value}
          </p>
          {change ? (
            <p
              className={cn(
                "text-xs font-medium",
                changePositive ? "text-emerald-400/90" : "text-zinc-500",
              )}
            >
              {change}
            </p>
          ) : null}
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900">
          <Icon className="h-4 w-4 text-zinc-400" strokeWidth={1.75} />
        </div>
      </div>
    </div>
  );
}
