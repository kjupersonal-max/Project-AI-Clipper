import type { ExportClipResponse } from "@/lib/api/projects";
import { resolveMediaUrl } from "@/lib/api/projects";
import { Badge } from "@/components/ui/Badge";
import { cn, formatDuration, formatFileSize } from "@/lib/utils";
import { CheckCircle2, Clock3, Download, Film, Video } from "lucide-react";

type ExportedClipsPanelProps = {
  exportedClips: ExportClipResponse[];
};

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

function statusVariant(
  status: string,
): "default" | "success" | "warning" | "info" | "muted" {
  switch (status) {
    case "completed":
      return "success";
    case "processing":
      return "warning";
    case "failed":
      return "info";
    default:
      return "default";
  }
}

function ExportedClipCard({ clip }: { clip: ExportClipResponse }) {
  const mediaUrl = resolveMediaUrl(clip.media_url);
  const displayName = clip.clip_name?.trim() || clip.filename;

  return (
    <div className="overflow-hidden rounded-lg border border-emerald-500/30 bg-zinc-950/50 ring-1 ring-emerald-500/10">
      <div className="space-y-4 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="success">Exported clip</Badge>
          <Badge variant={statusVariant(clip.export_status)}>{clip.export_status}</Badge>
        </div>

        <div>
          <p className="text-sm font-medium text-zinc-100">{displayName}</p>
          <p className="mt-1 font-mono text-xs text-zinc-500">{clip.filename}</p>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
          <span className="inline-flex items-center gap-1 font-mono text-emerald-300">
            <Clock3 className="h-3 w-3" />
            {formatTimestamp(clip.start_time)} → {formatTimestamp(clip.end_time)}
          </span>
          <span>Duration: {formatDuration(clip.duration)}</span>
          <span>Size: {formatFileSize(clip.file_size_bytes)}</span>
          <span>Created: {new Date(clip.created_at).toLocaleString()}</span>
        </div>

        <div className="overflow-hidden rounded-lg border border-zinc-800 bg-black">
          <video
            src={mediaUrl}
            controls
            preload="metadata"
            className="aspect-video w-full bg-black"
          >
            Your browser does not support HTML5 video playback.
          </video>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
        <p className="text-xs text-emerald-100/80">
          Rendered MP4 ready for download or preview.
        </p>
        <a
          href={mediaUrl}
          download={clip.filename}
          className={cn(
            "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-800",
          )}
        >
          <Download className="h-3.5 w-3.5" />
          Download
        </a>
      </div>
    </div>
  );
}

export function ExportedClipsPanel({ exportedClips }: ExportedClipsPanelProps) {
  if (exportedClips.length === 0) {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-6">
        <Video className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
        <div>
          <p className="text-sm text-zinc-500">
            No exported clips yet. Use Export on a clip candidate to render an MP4.
          </p>
          <p className="mt-2 text-xs text-zinc-600">
            Exported clips are shown for this browser session only. A backend list endpoint is
            needed to restore exports after a page refresh.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
        <Film className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
        <div>
          <p className="text-sm font-medium text-emerald-100">Rendered clip files</p>
          <p className="mt-1 text-sm text-emerald-100/80">
            These are exported MP4 files generated from clip candidates. Preview inline or download
            each clip.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {exportedClips.map((clip) => (
          <ExportedClipCard key={clip.clip_id} clip={clip} />
        ))}
      </div>

      <p className="text-xs text-zinc-600">
        Exports shown for this session. Refreshing the page clears this list until a backend list
        endpoint is available.
      </p>
    </div>
  );
}

export function ExportedClipsSummary({ count }: { count: number }) {
  if (count === 0) {
    return null;
  }

  return (
    <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
      <CheckCircle2 className="h-3.5 w-3.5" />
      {count} exported in this session
    </span>
  );
}
