import type { AnalysisDocument, SegmentAnalysis } from "@/lib/api/projects";
import {
  type AnalysisFilters,
  defaultAnalysisFilters,
  filterSegmentAnalysis,
} from "@/lib/analysis-filters";
import { Badge } from "@/components/ui/Badge";
import { cn, formatDuration } from "@/lib/utils";
import { AlertTriangle, ChevronDown, Clock3, Loader2, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

type TimelineAnalysisPanelProps = {
  analysis: AnalysisDocument;
  filters?: AnalysisFilters;
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
}: {
  seconds: number;
  onSeek: (seconds: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSeek(seconds)}
      className="inline-flex items-center gap-1 rounded-md border border-zinc-800 bg-zinc-950/70 px-2 py-0.5 font-mono text-xs text-emerald-300 transition-colors hover:border-emerald-500/40 hover:bg-emerald-500/10 hover:text-emerald-200"
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

function SegmentAnalysisCard({
  segment,
  expanded,
  onToggle,
  onSeek,
}: {
  segment: SegmentAnalysis;
  expanded: boolean;
  onToggle: () => void;
  onSeek: (seconds: number) => void;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border bg-zinc-950/50",
        segment.clip_candidate
          ? "border-amber-500/40 ring-1 ring-amber-500/20"
          : "border-zinc-800",
      )}
    >
      <div className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-900/70">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Collapse" : "Expand"} analysis for segment at ${formatTimestamp(segment.start)}`}
          className="mt-0.5 shrink-0 rounded p-0.5 text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform",
              expanded ? "rotate-0" : "-rotate-90",
            )}
          />
        </button>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <TimestampButton seconds={segment.start} onSeek={onSeek} />
            <span className="text-xs text-zinc-600">→</span>
            <TimestampButton seconds={segment.end} onSeek={onSeek} />
            <Badge variant="info">{segment.emotion}</Badge>
            {segment.clip_candidate ? (
              <Badge variant="warning">Clip candidate</Badge>
            ) : null}
          </div>

          <div
            role="button"
            tabIndex={0}
            aria-expanded={expanded}
            onClick={onToggle}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onToggle();
              }
            }}
            className="cursor-pointer text-sm text-zinc-200"
          >
            {segment.text}
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <ScorePill label="Excitement" value={segment.excitement_score} />
            <ScorePill label="Humor" value={segment.humor_score} />
            <ScorePill label="Suspense" value={segment.suspense_score} />
            <ScorePill label="Educational" value={segment.educational_score} />
            <ScorePill label="Standalone" value={segment.standalone_score} />
            <ScorePill label="Context dep." value={segment.context_dependency_score} />
          </div>
        </div>
      </div>

      {expanded ? (
        <div className="border-t border-zinc-800/80 px-4 py-3">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Reason</p>
          <p className="mt-2 text-sm leading-6 text-zinc-300">{segment.reason}</p>
        </div>
      ) : segment.clip_candidate ? (
        <div className="border-t border-amber-500/20 bg-amber-500/5 px-4 py-3">
          <p className="text-xs uppercase tracking-wider text-amber-300/80">Candidate reason</p>
          <p className="mt-1 text-sm text-amber-100/90">{segment.reason}</p>
        </div>
      ) : null}
    </div>
  );
}

export function TimelineAnalysisPanel({
  analysis,
  filters = defaultAnalysisFilters,
  onSeek,
}: TimelineAnalysisPanelProps) {
  const [expandedSegments, setExpandedSegments] = useState<Set<number>>(
    () => new Set(analysis.segments.filter((segment) => segment.clip_candidate).map((s) => s.segment_id)),
  );

  const filteredSegments = useMemo(
    () => filterSegmentAnalysis(analysis.segments, filters),
    [analysis.segments, filters],
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
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Provider</p>
          <p className="mt-2 text-sm font-medium capitalize text-zinc-100">{analysis.provider}</p>
          {analysis.model ? (
            <p className="mt-1 font-mono text-xs text-zinc-500">{analysis.model}</p>
          ) : null}
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Segments analyzed</p>
          <p className="mt-2 text-sm font-medium text-zinc-100">{analysis.segment_count}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Clip candidates</p>
          <p className="mt-2 text-sm font-medium text-amber-200">{analysis.clip_candidate_count}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Created</p>
          <p className="mt-2 text-sm font-medium text-zinc-100">
            {new Date(analysis.created_at).toLocaleString()}
          </p>
        </div>
      </div>

      {analysis.is_heuristic_fallback ? (
        <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <div>
            <p className="text-sm font-medium text-amber-100">Heuristic fallback analysis</p>
            <p className="mt-1 text-sm text-amber-100/80">
              These scores come from the local fallback analyzer, not a configured AI provider.
              Configure <span className="font-mono text-amber-200/90">ANALYSIS_API_KEY</span> and
              re-run Analyze to use OpenAI.
            </p>
          </div>
        </div>
      ) : analysis.provider === "openai" ? (
        <div className="flex items-start gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
          <div>
            <p className="text-sm font-medium text-emerald-100">OpenAI timeline analysis</p>
            <p className="mt-1 text-sm text-emerald-100/80">
              Scores were generated by OpenAI
              {analysis.model ? (
                <>
                  {" "}
                  using model <span className="font-mono text-emerald-200/90">{analysis.model}</span>
                </>
              ) : null}
              .
            </p>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
          <p className="text-sm text-emerald-100">
            Timeline analysis generated by configured provider{" "}
            <span className="font-medium capitalize">{analysis.provider}</span>
            {analysis.model ? (
              <>
                {" "}
                (<span className="font-mono">{analysis.model}</span>)
              </>
            ) : null}
            .
          </p>
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium text-zinc-200">
            Timeline segments ({filteredSegments.length})
          </h3>
          <p className="text-xs text-zinc-500">Click timestamps to seek the video preview</p>
        </div>

        {filteredSegments.length === 0 ? (
          <p className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-6 text-sm text-zinc-500">
            No segments match the current filters.
          </p>
        ) : (
          <div className="space-y-2">
            {filteredSegments.map((segment) => (
              <SegmentAnalysisCard
                key={segment.segment_id}
                segment={segment}
                expanded={expandedSegments.has(segment.segment_id)}
                onToggle={() => toggleSegment(segment.segment_id)}
                onSeek={onSeek}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function TimelineAnalysisState({
  loading,
  error,
  unavailableProvider,
}: {
  loading?: boolean;
  error?: string | null;
  unavailableProvider?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-zinc-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading timeline analysis...
      </div>
    );
  }

  if (unavailableProvider) {
    return (
      <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">
        <p className="font-medium">Analysis provider unavailable</p>
        <p className="mt-1 text-amber-100/80">{unavailableProvider}</p>
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

export function formatAnalysisDuration(seconds: number): string {
  return formatDuration(seconds);
}
