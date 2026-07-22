"use client";

import { cn } from "@/lib/utils";
import { mainNavItems } from "@/lib/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Scissors, X } from "lucide-react";

type SidebarProps = {
  open: boolean;
  onClose: () => void;
};

export function Sidebar({ open, onClose }: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity lg:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-zinc-800/80 bg-zinc-950 transition-transform duration-200 lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center justify-between border-b border-zinc-800/80 px-4 lg:h-16">
          <Link href="/" className="flex items-center gap-2.5" onClick={onClose}>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-100">
              <Scissors className="h-4 w-4 text-zinc-900" strokeWidth={2} />
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight text-zinc-100">
                AI Clipper
              </p>
              <p className="text-[10px] font-medium uppercase tracking-widest text-zinc-500">
                Studio
              </p>
            </div>
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300 lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="space-y-0.5">
            {mainNavItems.map((item) => {
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              const Icon = item.icon;

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onClose}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-zinc-900 text-zinc-100"
                        : "text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200",
                    )}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        isActive ? "text-zinc-200" : "text-zinc-500",
                      )}
                      strokeWidth={1.75}
                    />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="border-t border-zinc-800/80 p-4">
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-3">
            <p className="text-xs font-medium text-zinc-300">Pro Plan</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-500">
              842 clips generated this month
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}
