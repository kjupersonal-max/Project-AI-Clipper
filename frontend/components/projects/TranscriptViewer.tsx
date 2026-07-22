import type { AnalysisDocument, SegmentAnalysis, TranscriptDocument } from "@/lib/api/projects";
import { Badge } from "@/components/ui/Badge";
import {
  type AnalysisFilters,
  defaultAnalysisFilters,
  filterSegmentAnalysis,
  getEmotionOptions,
} from "@/lib/analysis-filters";
import { cn, formatDuration } from "@/lib/utils";
import { ChevronDown, Clock3, Filter, Languages, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";

type TranscriptViewerProps = {
  transcript: TranscriptDocument;
  analysis?: AnalysisDocument | null;
  filters?: AnalysisFilters;
  onFiltersChange?: (filters: AnalysisFilters) => void;
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

function ScorePill({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/70 px-2 py-1">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="text-xs font-medium text-zinc-100">{value.toFixed(1)}</p>
    </div>
  );
}

function SegmentAnalysisInline({ segment }: { segment: SegmentAnalysis }) {
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-3",
        segment.clip_candidate
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-zinc-800 bg-zinc-900/50",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="info">{segment.emotion}</Badge>
        {segment.clip_candidate ? <Badge variant="warning">Clip candidate</Badge> : null}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <ScorePill label="Excitement" value={segment.excitement_score} />
        <ScorePill label="Humor" value={segment.humor_score} />
        <ScorePill label="Suspense" value={segment.suspense_score} />
        <ScorePill label="Educational" value={segment.educational_score} />
      </div>
      <p className="mt-3 text-xs leading-5 text-zinc-400">{segment.reason}</p>
    </div>
  );
}

function AnalysisFilterBar({
  filters,
  emotions,
  onChange,
}: {
  filters: AnalysisFilters;
  emotions: string[];
  onChange: (filters: AnalysisFilters) => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-zinc-500">
        <Filter className="h-3.5 w-3.5" />
        Analysis filters
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={filters.clipCandidatesOnly}
            onChange={(event) =>
              onChange({ ...filters, clipCandidatesOnly: event.target.checked })
            }
            className="rounded border-zinc-700 bg-zinc-900"
          />
          Clip candidates only
        </label>
        <label className="space-y-1 text-sm text-zinc-300">
          <span className="block text-xs uppercase tracking-wider text-zinc-500">
            Minimum excitement
          </span>
          <input
            type="range"
            min={0}
            max={10}
            step={0.5}
            value={filters.minExcitement}
            onChange={(event) =>
              onChange({ ...filters, minExcitement: Number(event.target.value) })
            }
            className="w-full"
          />
          <span className="text-xs text-zinc-500">{filters.minExcitement.toFixed(1)} / 10</span>
        </label>
        <label className="space-y-1 text-sm text-zinc-300">
          <span className="block text-xs uppercase tracking-wider text-zinc-500">Emotion</span>
          <select
            value={filters.emotion}
            onChange={(event) => onChange({ ...filters, emotion: event.target.value })}
            className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-sm text-zinc-200"
          >
            {emotions.map((emotion) => (
              <option key={emotion} value={emotion}>
                {emotion === "all" ? "All emotions" : emotion}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

export function TranscriptViewer({
  transcript,
  analysis,
  filters = defaultAnalysisFilters,
  onFiltersChange,
  onSeek,
}: TranscriptViewerProps) {
  const [expandedSegments, setExpandedSegments] = useState<Set<number>>(
    () => new Set([transcript.segments[0]?.id]),
  );

  const analysisBySegmentId = useMemo(() => {
    if (!analysis) return new Map<number, SegmentAnalysis>();
    return new Map(analysis.segments.map((segment) => [segment.segment_id, segment]));
  }, [analysis]);

  const filteredAnalysisIds = useMemo(() => {
    if (!analysis) return null;
    return new Set(filterSegmentAnalysis(analysis.segments, filters).map((s) => s.segment_id));
  }, [analysis, filters]);

  const emotions = useMemo(
    () => (analysis ? getEmotionOptions(analysis.segments) : ["all"]),
    [analysis],
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

      {analysis && onFiltersChange ? (
        <AnalysisFilterBar filters={filters} emotions={emotions} onChange={onFiltersChange} />
      ) : null}

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium text-zinc-200">
            Segments
            {filteredAnalysisIds != null
              ? ` (${transcript.segments.filter((segment) => filteredAnalysisIds.has(segment.id)).length} with analysis)`
              : ""}
          </h3>
          <p className="text-xs text-zinc-500">Click timestamps to seek the video preview</p>
        </div>

        <div className="space-y-2">
          {transcript.segments.map((segment) => {
            const expanded = expandedSegments.has(segment.id);
            const segmentAnalysis = analysisBySegmentId.get(segment.id);
            const hiddenByFilter =
              filteredAnalysisIds != null &&
              segmentAnalysis != null &&
              !filteredAnalysisIds.has(segment.id);

            if (hiddenByFilter) {
              return null;
            }

            return (
              <div
                key={segment.id}
                className={cn(
                  "overflow-hidden rounded-lg border bg-zinc-950/50",
                  segmentAnalysis?.clip_candidate
                    ? "border-amber-500/40 ring-1 ring-amber-500/20"
                    : "border-zinc-800",
                )}
              >
                <div className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-900/70">
                  <button
                    type="button"
                    onClick={() => toggleSegment(segment.id)}
                    aria-expanded={expanded}
                    aria-label={`${expanded ? "Collapse" : "Expand"} segment at ${formatTimestamp(segment.start)}`}
                    className="mt-0.5 shrink-0 rounded p-0.5 text-zinc-500 transition-colors hover:text-zinc-300"
                  >
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 transition-transform",
                        expanded ? "rotate-0" : "-rotate-90",
                      )}
                    />
                  </button>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <TimestampButton seconds={segment.start} onSeek={onSeek} />
                      <span className="text-xs text-zinc-600">→</span>
                      <TimestampButton seconds={segment.end} onSeek={onSeek} />
                    </div>
                    <div
                      role="button"
                      tabIndex={0}
                      aria-expanded={expanded}
                      onClick={() => toggleSegment(segment.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          toggleSegment(segment.id);
                        }
                      }}
                      className="cursor-pointer text-sm text-zinc-200"
                    >
                      {segment.text}
                    </div>
                    {segmentAnalysis ? (
                      <SegmentAnalysisInline segment={segmentAnalysis} />
                    ) : null}
                  </div>
                </div>

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
