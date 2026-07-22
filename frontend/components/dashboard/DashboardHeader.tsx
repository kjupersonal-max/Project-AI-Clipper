import { Button } from "@/components/ui/Button";
import { Upload } from "lucide-react";
import Link from "next/link";

export function DashboardHeader() {
  return (
    <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50 sm:text-3xl">
          Project AI Clipper
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-zinc-400">
          Analyze long-form VODs, surface high-retention clip candidates, and
          prepare polished shorts for publishing — all from one workspace.
        </p>
      </div>
      <Link href="/upload" className="w-full shrink-0 sm:w-auto">
        <Button
          size="lg"
          className="w-full"
          icon={<Upload className="h-4 w-4" />}
        >
          Upload New VOD
        </Button>
      </Link>
    </div>
  );
}
