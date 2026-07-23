"use client";

import type { Project, VisualAnalysisDocument } from "@/lib/api/projects";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn, formatDuration } from "@/lib/utils";
import { AlertTriangle, Eye, Loader2 } from "lucide-react";

type VisualAnalysisPanelProps = {
  project: Project;
  visualAnalysis: VisualAnalysisDocument | null;
  loading: boolean;
  running: boolean;
  error: string | null;
  onRun: (force?: boolean) => void;
};

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
    case "unavailable":
      return "muted";
    default:
      return "default";
  }
}

export function VisualAnalysisPanel({
  project,
  visualAnalysis,
  loading,
  running,
  error,
  onRun,
}: VisualAnalysisPanelProps) {
  const status = project.visual_analysis_status;
  const canRun =
    project.inspection_status === "completed" &&
    status !== "processing" &&
    status !== "unavailable" &&
    !running;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={statusVariant(status)}>{status.replace("_", " ")}</Badge>
        {project.visual_analysis_duration_seconds != null ? (
          <Badge variant="muted">
            {project.visual_analysis_duration_seconds.toFixed(2)}s processing
          </Badge>
        ) : null}
        {project.visual_analysis_sampled_frame_count != null ? (
          <Badge variant="muted">
            {project.visual_analysis_sampled_frame_count} sampled frames
          </Badge>
        ) : null}
        {project.visual_analysis_window_count != null ? (
          <Badge variant="muted">
            {project.visual_analysis_window_count} visual windows
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => onRun(false)}
          disabled={!canRun || loading}
          icon={
            running ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Eye className="h-4 w-4" />
            )
          }
        >
          {running ? "Analyzing visuals..." : status === "completed" ? "Rerun Visual Analysis" : "Run Visual Analysis"}
        </Button>
        {status === "completed" ? (
          <Button
            variant="secondary"
            onClick={() => onRun(true)}
            disabled={!canRun || loading || running}
          >
            Force refresh
          </Button>
        ) : null}
      </div>

      {status === "unavailable" ? (
        <div className="rounded-md border border-zinc-800 bg-zinc-950/50 px-3 py-2 text-sm text-zinc-400">
          Visual analysis is unavailable on this environment. Clip selection will use transcript-only
          scoring.
        </div>
      ) : null}

      {error ? (
        <div className="flex items-start gap-2 rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2 text-sm text-red-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading visual analysis results...
        </div>
      ) : null}

      {visualAnalysis?.warnings && visualAnalysis.warnings.length > 0 ? (
        <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wider text-amber-300/80">Warnings</p>
          <ul className="mt-1 space-y-1 text-xs text-amber-100/90">
            {visualAnalysis.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {visualAnalysis && visualAnalysis.windows.length > 0 ? (
        <details className="rounded-md border border-zinc-800/80 bg-zinc-950/40 px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-zinc-400">
            Sample visual windows ({Math.min(visualAnalysis.windows.length, 8)} shown)
          </summary>
          <ul className="mt-2 space-y-2">
            {visualAnalysis.windows.slice(0, 8).map((window) => (
              <li
                key={`${window.start}-${window.end}`}
                className="rounded border border-zinc-800/80 bg-zinc-950/60 px-2 py-1.5 text-xs text-zinc-300"
              >
                <span className="font-mono text-emerald-300">
                  {formatDuration(window.start)} → {formatDuration(window.end)}
                </span>
                <span className="mx-2 text-zinc-600">·</span>
                activity {window.activity_score.toFixed(1)} ({window.activity_label})
                {window.events.length > 0 ? (
                  <span className="ml-2 text-zinc-500">{window.events.join(", ")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {status === "not_started" && !running ? (
        <p className="text-sm text-zinc-500">
          Optional lightweight frame sampling for motion, scene changes, and visual continuity. Run
          before Select Clips to improve ranking and boundaries.
        </p>
      ) : null}
    </div>
  );
}

export function VisualAnalysisState({
  loading,
  error,
}: {
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className={cn("flex items-center gap-2 text-sm text-zinc-500")}>
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading visual analysis...
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-red-300">{error}</p>;
  }

  return null;
}
