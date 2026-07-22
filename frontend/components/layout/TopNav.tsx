"use client";

import { Button } from "@/components/ui/Button";
import { Bell, Menu, Search, Upload } from "lucide-react";
import Link from "next/link";

type TopNavProps = {
  onMenuClick: () => void;
};

export function TopNav({ onMenuClick }: TopNavProps) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-4 border-b border-zinc-800/80 bg-zinc-950/80 px-4 backdrop-blur-md lg:h-16 lg:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200 lg:hidden"
        aria-label="Open sidebar"
      >
        <Menu className="h-5 w-5" />
      </button>

      <div className="relative hidden flex-1 sm:block sm:max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <input
          type="search"
          placeholder="Search projects, clips, VODs..."
          className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 pl-9 pr-4 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-700 focus:outline-none focus:ring-1 focus:ring-zinc-700"
        />
      </div>

      <div className="ml-auto flex items-center gap-2">
        <Link href="/upload" className="hidden sm:inline-flex">
          <Button
            variant="secondary"
            size="sm"
            icon={<Upload className="h-3.5 w-3.5" />}
          >
            Quick Upload
          </Button>
        </Link>
        <button
          type="button"
          className="relative rounded-md p-2 text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-zinc-400" />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-full border border-zinc-700 bg-zinc-800 text-xs font-medium text-zinc-300">
          AC
        </div>
      </div>
    </header>
  );
}
