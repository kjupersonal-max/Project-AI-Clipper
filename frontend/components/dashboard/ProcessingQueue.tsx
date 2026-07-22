import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { processingQueue, type QueueItem } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

const stageLabels: Record<QueueItem["stage"], string> = {
  transcribing: "Transcribing",
  analyzing: "Analyzing",
  generating: "Generating clips",
  rendering: "Rendering",
};

export function ProcessingQueue() {
  const queue = processingQueue;

  return (
    <Card>
      <CardHeader
        title="Processing Queue"
        description="Active VOD analysis and clip generation jobs"
      />
      <CardContent className="p-0">
        {queue.length === 0 ? (
          <EmptyState
            icon={Loader2}
            title="Queue is empty"
            description="No VODs are currently being processed. Upload a new VOD to get started."
          />
        ) : (
          <ul className="divide-y divide-zinc-800/60">
            {queue.map((item) => (
              <li key={item.id} className="px-5 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-zinc-200">
                      {item.title}
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {stageLabels[item.stage]} · ETA {item.eta}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs font-medium tabular-nums text-zinc-400">
                    {item.progress}%
                  </span>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className={cn(
                      "h-full rounded-full bg-zinc-400 transition-all",
                      item.progress >= 80 && "bg-zinc-200",
                    )}
                    style={{ width: `${item.progress}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
