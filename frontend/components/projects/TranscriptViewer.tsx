import type { TranscriptDocument } from "@/lib/api/projects";
import { cn, formatDuration } from "@/lib/utils";
import { ChevronDown, Clock3, Languages, Loader2 } from "lucide-react";
import { useState } from "react";

type TranscriptViewerProps = {
  transcript: TranscriptDocument;
  onSeek: (seconds: number) => void;
};

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

function TimestampButton({
  seconds,
  onSeek,
  className,
}: {
  seconds: number;
  onSeek: (seconds: number) => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onSeek(seconds)}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-zinc-800 bg-zinc-950/70 px-2 py-0.5 font-mono text-xs text-emerald-300 transition-colors hover:border-emerald-500/40 hover:bg-emerald-500/10 hover:text-emerald-200",
        className,
      )}
      title={`Seek to ${formatTimestamp(seconds)}`}
    >
      <Clock3 className="h-3 w-3" />
      {formatTimestamp(seconds)}
    </button>
  );
}

export function TranscriptViewer({ transcript, onSeek }: TranscriptViewerProps) {
  const [expandedSegments, setExpandedSegments] = useState<Set<number>>(
    () => new Set([transcript.segments[0]?.id]),
  );

  const toggleSegment = (segmentId: number) => {
    setExpandedSegments((current) => {
      const next = new Set(current);
      if (next.has(segmentId)) {
        next.delete(segmentId);
      } else {
        next.add(segmentId);
      }
      return next;
    });
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-zinc-500">
            <Languages className="h-3.5 w-3.5" />
            Language
          </div>
          <p className="mt-2 text-sm font-medium uppercase text-zinc-100">
            {transcript.language}
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-zinc-500">
            <Clock3 className="h-3.5 w-3.5" />
            Duration
          </div>
          <p className="mt-2 text-sm font-medium text-zinc-100">
            {formatDuration(transcript.duration)}
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Coverage</p>
          <p className="mt-2 text-sm font-medium text-zinc-100">
            {transcript.segment_count} segments · {transcript.word_count} words
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
        <p className="text-xs uppercase tracking-wider text-zinc-500">Full transcript</p>
        <p className="mt-3 text-sm leading-7 text-zinc-300">
          {transcript.segments.map((segment) => segment.text).join(" ")}
        </p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium text-zinc-200">Segments</h3>
          <p className="text-xs text-zinc-500">Click timestamps to seek the video preview</p>
        </div>

        <div className="space-y-2">
          {transcript.segments.map((segment) => {
            const expanded = expandedSegments.has(segment.id);

            return (
              <div
                key={segment.id}
                className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/50"
              >
                <button
                  type="button"
                  onClick={() => toggleSegment(segment.id)}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-900/70"
                >
                  <ChevronDown
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0 text-zinc-500 transition-transform",
                      expanded ? "rotate-0" : "-rotate-90",
                    )}
                  />
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <TimestampButton seconds={segment.start} onSeek={onSeek} />
                      <span className="text-xs text-zinc-600">→</span>
                      <TimestampButton seconds={segment.end} onSeek={onSeek} />
                    </div>
                    <p className="text-sm text-zinc-200">{segment.text}</p>
                  </div>
                </button>

                {expanded ? (
                  <div className="border-t border-zinc-800/80 px-4 py-3">
                    <p className="mb-2 text-xs uppercase tracking-wider text-zinc-500">
                      Word timestamps
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {segment.words.map((word, index) => (
                        <button
                          key={`${segment.id}-${index}-${word.start}`}
                          type="button"
                          onClick={() => onSeek(word.start)}
                          className="rounded-md border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-left transition-colors hover:border-emerald-500/40 hover:bg-emerald-500/10"
                        >
                          <span className="block font-mono text-[10px] text-emerald-300">
                            {formatTimestamp(word.start)}
                          </span>
                          <span className="block text-xs text-zinc-200">{word.word}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function TranscriptViewerState({
  loading,
  error,
}: {
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-zinc-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading transcript...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-300">
        {error}
      </div>
    );
  }

  return null;
}
