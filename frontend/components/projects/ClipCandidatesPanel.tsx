import type { ClipCandidate, ClipCandidatesDocument } from "@/lib/api/projects";
import {
  type ClipCandidateFilters,
  filterAndSortClipCandidates,
  getClipEmotionOptions,
} from "@/lib/clip-candidate-filters";
import type { CandidateExportState } from "@/lib/clip-export";
import {
  isCandidateExported,
  isCandidateExporting,
} from "@/lib/clip-export";
import {
  candidateCaptionStatusLabel,
  type CandidateCaptionState,
} from "@/lib/candidate-captions";
import { Badge } from "@/components/ui/Badge";
import { ClipExportButton } from "@/components/projects/ClipExportButton";
import { formatDuration, uniqueStringListItems } from "@/lib/utils";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Film,
  Loader2,
  RefreshCw,
  Scissors,
  Sparkles,
  Subtitles,
} from "lucide-react";
import { useMemo } from "react";

type ClipCandidatesPanelProps = {
  clipCandidates: ClipCandidatesDocument;
  filters: ClipCandidateFilters;
  onFiltersChange: (filters: ClipCandidateFilters) => void;
  onSeek: (seconds: number) => void;
  exportStates?: Record<string, CandidateExportState>;
  exportedCandidateIds?: ReadonlySet<string>;
  captionStates?: Record<string, CandidateCaptionState>;
  onExport?: (candidate: ClipCandidate) => void;
  onGenerateCaptions?: (candidate: ClipCandidate) => void;
  onEditCaptions?: (candidate: ClipCandidate) => void;
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

function ImportancePill({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-zinc-800/80 bg-zinc-900/50 px-2 py-1">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="text-xs font-medium text-zinc-200">{value.toFixed(1)}</p>
    </div>
  );
}

function ClipCandidateCard({
  candidate,
  rank,
  onSeek,
  exportState,
  isExported,
  isExporting,
  captionState,
  onExport,
  onGenerateCaptions,
  onEditCaptions,
}: {
  candidate: ClipCandidate;
  rank: number;
  onSeek: (seconds: number) => void;
  exportState?: CandidateExportState;
  isExported: boolean;
  isExporting: boolean;
  captionState?: CandidateCaptionState;
  onExport?: (candidate: ClipCandidate) => void;
  onGenerateCaptions?: (candidate: ClipCandidate) => void;
  onEditCaptions?: (candidate: ClipCandidate) => void;
}) {
  const captionStatus = captionState?.status ?? "not_generated";
  const captionBusy = captionStatus === "generating";
  const importance = candidate.importance_breakdown;
  const selectionReasons =
    candidate.selection_reasons && candidate.selection_reasons.length > 0
      ? candidate.selection_reasons
      : [candidate.reason];
  const visualContribution = candidate.score_breakdown?.visual_contribution ?? 0;
  const hasMeaningfulVisual =
    (candidate.visual_evidence?.visual_contribution ?? 0) !== 0 ||
    (candidate.visual_evidence?.measured_signals?.length ?? 0) > 0 ||
    Math.abs(visualContribution) >= 0.5;

  return (
    <div className="overflow-hidden rounded-lg border border-amber-500/30 bg-zinc-950/50 ring-1 ring-amber-500/10">
      <div className="space-y-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="warning">Final clip #{rank}</Badge>
          <Badge variant="info">{candidate.status}</Badge>
          <Badge variant="default">Score {candidate.score.toFixed(1)}</Badge>
          <Badge variant="muted">Confidence {(candidate.confidence * 100).toFixed(0)}%</Badge>
          <Badge
            variant={
              captionStatus === "completed"
                ? "success"
                : captionStatus === "failed"
                  ? "info"
                  : captionStatus === "generating"
                    ? "warning"
                    : "muted"
            }
          >
            {candidateCaptionStatusLabel(captionStatus)}
          </Badge>
          {isExported ? (
            <Badge variant="success">
              <CheckCircle2 className="mr-1 inline h-3 w-3" />
              Exported
            </Badge>
          ) : null}
        </div>

        <div>
          <p className="text-sm font-medium text-zinc-100">{candidate.title_suggestion}</p>
          <p className="mt-1 text-xs text-zinc-500">
            Not a rendered video file — this is a proposed clip range on the source upload.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <TimestampButton seconds={candidate.start} onSeek={onSeek} />
          <span className="text-xs text-zinc-600">→</span>
          <TimestampButton seconds={candidate.end} onSeek={onSeek} />
          <Badge variant="info">{candidate.primary_emotion}</Badge>
          <span className="text-xs text-zinc-500">
            Duration: {formatDuration(candidate.duration)}
          </span>
        </div>

        <p className="text-sm leading-6 text-zinc-300">{candidate.transcript_text}</p>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <ScorePill label="Hook" value={candidate.hook_score} />
          <ScorePill label="Payoff" value={candidate.payoff_score} />
          <ScorePill label="Standalone" value={candidate.standalone_score} />
          <ScorePill label="Context dep." value={candidate.context_dependency_score} />
        </div>

        {importance ? (
          <details className="rounded-md border border-zinc-800/80 bg-zinc-950/40 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-zinc-400">
              Importance breakdown
            </summary>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <ImportancePill label="Hook" value={importance.hook} />
              <ImportancePill label="Emotion" value={importance.emotion} />
              <ImportancePill label="Story" value={importance.story_value} />
              <ImportancePill label="Info" value={importance.information_value} />
              <ImportancePill label="Retention" value={importance.retention} />
              <ImportancePill label="Share" value={importance.shareability} />
              <ImportancePill label="Standalone" value={importance.standalone_quality} />
              <ImportancePill label="Monetize" value={importance.monetization_potential} />
            </div>
          </details>
        ) : null}

        {hasMeaningfulVisual ? (
          <div className="rounded-md border border-violet-500/20 bg-violet-500/5 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-violet-300/80">
              Visual evidence
            </p>
            {visualContribution !== 0 ? (
              <p className="mt-1 text-xs text-violet-100/90">
                Score contribution: {visualContribution > 0 ? "+" : ""}
                {visualContribution.toFixed(1)}
                {candidate.score_breakdown?.transcript_only_score != null ? (
                  <span className="text-zinc-500">
                    {" "}
                    (transcript {candidate.score_breakdown.transcript_only_score.toFixed(1)} → combined{" "}
                    {candidate.score.toFixed(1)})
                  </span>
                ) : null}
              </p>
            ) : null}
            {candidate.visual_evidence?.measured_signals &&
            candidate.visual_evidence.measured_signals.length > 0 ? (
              <p className="mt-1 text-xs text-violet-100/80">
                Signals: {candidate.visual_evidence.measured_signals.join(", ")}
              </p>
            ) : null}
          </div>
        ) : null}

        {candidate.warnings && candidate.warnings.length > 0 ? (
          <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-amber-300/80">Warnings</p>
            <ul className="mt-1 space-y-1 text-xs text-amber-100/90">
              {uniqueStringListItems(candidate.warnings, "candidate-warning").map((warning) => (
                <li key={warning.key}>{warning.text}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {onGenerateCaptions || onEditCaptions || onExport ? (
          <div className="space-y-3 border-t border-zinc-800/80 pt-3">
            {onGenerateCaptions || onEditCaptions ? (
              <div className="flex flex-wrap items-center gap-2">
                {captionStatus === "completed" && onEditCaptions ? (
                  <button
                    type="button"
                    onClick={() => onEditCaptions(candidate)}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-medium text-emerald-100 transition-colors hover:bg-emerald-500/20"
                  >
                    <Subtitles className="h-4 w-4" />
                    Edit captions
                  </button>
                ) : null}
                {captionStatus !== "completed" && onGenerateCaptions ? (
                  <button
                    type="button"
                    onClick={() => onGenerateCaptions(candidate)}
                    disabled={captionBusy}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 text-sm font-medium text-sky-100 transition-colors hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {captionBusy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : captionStatus === "failed" ? (
                      <RefreshCw className="h-4 w-4" />
                    ) : (
                      <Sparkles className="h-4 w-4" />
                    )}
                    {captionBusy
                      ? "Generating captions..."
                      : captionStatus === "failed"
                        ? "Retry captions"
                        : "Generate captions"}
                  </button>
                ) : null}
              </div>
            ) : null}
            {captionState?.error ? (
              <p className="text-xs text-red-300">{captionState.error}</p>
            ) : null}
            {onExport ? (
              <ClipExportButton
                exportState={exportState}
                isExported={isExported}
                isExporting={isExporting}
                onExport={() => onExport(candidate)}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="border-t border-amber-500/20 bg-amber-500/5 px-4 py-3">
        <p className="text-xs uppercase tracking-wider text-amber-300/80">Why this clip</p>
        <ul className="mt-1 space-y-1 text-sm text-amber-100/90">
          {uniqueStringListItems(selectionReasons, "selection-reason").map((item) => (
            <li key={item.key}>• {item.text}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function ClipCandidatesPanel({
  clipCandidates,
  filters,
  onFiltersChange,
  onSeek,
  exportStates = {},
  exportedCandidateIds = new Set<string>(),
  captionStates = {},
  onExport,
  onGenerateCaptions,
  onEditCaptions,
}: ClipCandidatesPanelProps) {
  const emotionOptions = useMemo(
    () => getClipEmotionOptions(clipCandidates.candidates),
    [clipCandidates.candidates],
  );

  const filteredCandidates = useMemo(
    () => filterAndSortClipCandidates(clipCandidates.candidates, filters),
    [clipCandidates.candidates, filters],
  );

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
        <Film className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
        <div>
          <p className="text-sm font-medium text-amber-100">Final clip candidates</p>
          <p className="mt-1 text-sm text-amber-100/80">
            {clipCandidates.candidate_count} selected clip
            {clipCandidates.candidate_count === 1 ? "" : "s"} ready for captions and export. Each
            candidate is a ranked time range on the source upload — not a rendered video file yet.
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Final clips</p>
          <p className="mt-2 text-sm font-medium text-amber-200">{clipCandidates.candidate_count}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Duration limits</p>
          <p className="mt-2 text-sm font-medium text-zinc-100">
            {formatDuration(clipCandidates.min_duration_seconds)} –{" "}
            {formatDuration(clipCandidates.max_duration_seconds)}
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Max gap</p>
          <p className="mt-2 text-sm font-medium text-zinc-100">
            {clipCandidates.max_gap_seconds.toFixed(1)}s
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Created</p>
          <p className="mt-2 text-sm font-medium text-zinc-100">
            {new Date(clipCandidates.created_at).toLocaleString()}
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
        <div className="mb-4 flex items-center gap-2">
          <Scissors className="h-4 w-4 text-zinc-500" />
          <h3 className="text-sm font-medium text-zinc-200">Filter and sort</h3>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <label className="space-y-2 text-sm">
            <span className="text-zinc-500">Minimum score</span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={filters.minScore}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  minScore: Number(event.target.value) || 0,
                })
              }
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-100"
            />
          </label>
          <label className="space-y-2 text-sm">
            <span className="text-zinc-500">Min duration (s)</span>
            <input
              type="number"
              min={0}
              step={1}
              value={filters.minDuration}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  minDuration: Number(event.target.value) || 0,
                })
              }
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-100"
            />
          </label>
          <label className="space-y-2 text-sm">
            <span className="text-zinc-500">Max duration (s)</span>
            <input
              type="number"
              min={0}
              step={1}
              value={filters.maxDuration}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  maxDuration: Number(event.target.value) || 0,
                })
              }
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-100"
            />
          </label>
          <label className="space-y-2 text-sm">
            <span className="text-zinc-500">Primary emotion</span>
            <select
              value={filters.emotion}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  emotion: event.target.value,
                })
              }
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-100"
            >
              {emotionOptions.map((emotion) => (
                <option key={emotion} value={emotion}>
                  {emotion}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm">
            <span className="text-zinc-500">Sort by</span>
            <select
              value={filters.sort}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  sort: event.target.value as ClipCandidateFilters["sort"],
                })
              }
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-100"
            >
              <option value="score">Highest score</option>
              <option value="shortest">Shortest</option>
              <option value="longest">Longest</option>
              <option value="earliest">Earliest in video</option>
            </select>
          </label>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium text-zinc-200">
            Final clip candidates ({filteredCandidates.length})
          </h3>
          <p className="text-xs text-zinc-500">Click timestamps to seek the source video</p>
        </div>

        {clipCandidates.candidate_count === 0 ? (
          <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-6">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
            <p className="text-sm text-zinc-500">
              No proposed clips met the selection thresholds for this project.
            </p>
          </div>
        ) : filteredCandidates.length === 0 ? (
          <p className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-6 text-sm text-zinc-500">
            No candidates match the current filters.
          </p>
        ) : (
          <div className="space-y-3">
            {filteredCandidates.map((candidate, index) => (
              <ClipCandidateCard
                key={candidate.clip_id}
                candidate={candidate}
                rank={index + 1}
                onSeek={onSeek}
                exportState={exportStates[candidate.clip_id]}
                isExported={isCandidateExported(
                  candidate.clip_id,
                  exportedCandidateIds,
                  exportStates,
                )}
                isExporting={isCandidateExporting(candidate.clip_id, exportStates)}
                captionState={captionStates[candidate.clip_id]}
                onExport={onExport}
                onGenerateCaptions={onGenerateCaptions}
                onEditCaptions={onEditCaptions}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function ClipCandidatesState({
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
        Loading clip candidates...
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
