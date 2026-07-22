"use client";

import {
  extractProjectAudio,
  fetchProject,
  getProjectVideoUrl,
  inspectProject,
  type ApiError,
  type Project,
} from "@/lib/api/projects";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { cn, formatFileSize } from "@/lib/utils";
import {
  AlertCircle,
  AudioLines,
  CheckCircle2,
  Loader2,
  ScanSearch,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

type ProjectDetailsProps = {
  projectId: string;
};

type ActionState = "idle" | "loading" | "success" | "error";

const statusVariant = (
  status: string,
): "default" | "success" | "warning" | "info" | "muted" => {
  switch (status) {
    case "completed":
      return "success";
    case "processing":
      return "warning";
    case "failed":
      return "info";
    case "skipped":
      return "muted";
    default:
      return "default";
  }
};

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return minutes > 0 ? `${minutes}m ${remaining}s` : `${remaining}s`;
}

function formatFrameRate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value.toFixed(2)} fps`;
}

export function ProjectDetails({ projectId }: ProjectDetailsProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [inspectState, setInspectState] = useState<ActionState>("idle");
  const [extractState, setExtractState] = useState<ActionState>("idle");
  const [actionError, setActionError] = useState<string | null>(null);

  const loadProject = useCallback(async () => {
    setPageError(null);

    try {
      const data = await fetchProject(projectId);
      setProject(data);
      return data;
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to load project.";
      setPageError(message);
      setProject(null);
      return null;
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;

    async function initializeProject() {
      setLoading(true);
      setPageError(null);

      try {
        const data = await fetchProject(projectId);
        if (!cancelled) {
          setProject(data);
        }
      } catch (error) {
        if (!cancelled) {
          const message =
            error && typeof error === "object" && "message" in error
              ? String((error as ApiError).message)
              : "Unable to load project.";
          setPageError(message);
          setProject(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void initializeProject();

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const refreshProject = async () => {
    setLoading(true);
    await loadProject();
    setLoading(false);
  };

  const handleInspect = async () => {
    setInspectState("loading");
    setActionError(null);

    try {
      await inspectProject(projectId);
      setInspectState("success");
      await refreshProject();
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Inspection failed.";
      setActionError(message);
      setInspectState("error");
      await refreshProject();
    }
  };

  const handleExtractAudio = async () => {
    setExtractState("loading");
    setActionError(null);

    try {
      await extractProjectAudio(projectId);
      setExtractState("success");
      await refreshProject();
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Audio extraction failed.";
      setActionError(message);
      setExtractState("error");
      await refreshProject();
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-zinc-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading project...
      </div>
    );
  }

  if (pageError || !project) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 p-6">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
          <div>
            <p className="text-sm font-medium text-zinc-200">
              Unable to load project
            </p>
            <p className="mt-1 text-sm text-red-300">{pageError}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const metadata = project.video_metadata;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(project.upload_status)}>
              Upload: {project.upload_status}
            </Badge>
            <Badge variant={statusVariant(project.inspection_status)}>
              Inspection: {project.inspection_status}
            </Badge>
            <Badge variant={statusVariant(project.audio_extraction_status)}>
              Audio: {project.audio_extraction_status}
            </Badge>
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-50 sm:text-3xl">
              {project.original_filename}
            </h1>
            <p className="mt-2 break-all font-mono text-xs text-zinc-500">
              {project.project_id}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={handleInspect}
            disabled={inspectState === "loading" || extractState === "loading"}
            icon={
              inspectState === "loading" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ScanSearch className="h-4 w-4" />
              )
            }
          >
            Inspect Video
          </Button>
          <Button
            onClick={handleExtractAudio}
            disabled={inspectState === "loading" || extractState === "loading"}
            icon={
              extractState === "loading" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <AudioLines className="h-4 w-4" />
              )
            }
          >
            Extract Audio
          </Button>
        </div>
      </div>

      {actionError ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
            <p className="text-sm text-red-300">{actionError}</p>
          </CardContent>
        </Card>
      ) : null}

      {(inspectState === "success" || extractState === "success") && !actionError ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
            <p className="text-sm text-emerald-300">
              {extractState === "success"
                ? "Audio extraction completed. Project state refreshed."
                : "Video inspection completed. Project state refreshed."}
            </p>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title="Video Preview" description="Uploaded source file" />
          <CardContent>
            <div className="overflow-hidden rounded-lg border border-zinc-800 bg-black">
              <video
                src={getProjectVideoUrl(project.project_id)}
                controls
                className="aspect-video w-full bg-black object-contain"
                preload="metadata"
              />
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6 xl:col-span-2">
          <Card>
            <CardHeader
              title="Video Metadata"
              description={
                project.inspection_status === "completed"
                  ? "Results from ffprobe"
                  : "Run inspection to populate metadata"
              }
            />
            <CardContent>
              {metadata ? (
                <dl className="grid gap-3 text-sm">
                  {[
                    ["Duration", formatDuration(metadata.duration_seconds)],
                    ["Resolution", metadata.width && metadata.height ? `${metadata.width}×${metadata.height}` : "—"],
                    ["Frame rate", formatFrameRate(metadata.frame_rate)],
                    ["Aspect ratio", metadata.aspect_ratio ?? "—"],
                    ["Video codec", metadata.video_codec ?? "—"],
                    ["Audio codec", metadata.audio_codec ?? "—"],
                    ["Sample rate", metadata.sample_rate ? `${metadata.sample_rate} Hz` : "—"],
                    ["Channels", metadata.audio_channels?.toString() ?? "—"],
                    ["File size", metadata.file_size ? formatFileSize(metadata.file_size) : formatFileSize(project.size_bytes)],
                    ["Has video", metadata.has_video ? "Yes" : "No"],
                    ["Has audio", metadata.has_audio ? "Yes" : "No"],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="flex items-center justify-between gap-4 border-b border-zinc-800/60 pb-3 last:border-b-0 last:pb-0"
                    >
                      <dt className="text-zinc-500">{label}</dt>
                      <dd className="text-right text-zinc-200">{value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-zinc-500">
                  No metadata yet. Click Inspect Video to analyze this upload.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader title="Processing Status" />
            <CardContent className="space-y-4 text-sm">
              <div className="flex items-center justify-between gap-4">
                <span className="text-zinc-500">Upload</span>
                <Badge variant={statusVariant(project.upload_status)}>
                  {project.upload_status}
                </Badge>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-zinc-500">Inspection</span>
                <Badge variant={statusVariant(project.inspection_status)}>
                  {project.inspection_status}
                </Badge>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-zinc-500">Audio extraction</span>
                <Badge variant={statusVariant(project.audio_extraction_status)}>
                  {project.audio_extraction_status}
                </Badge>
              </div>
              {project.extracted_audio_path ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                  <p className="text-xs uppercase tracking-wider text-zinc-500">
                    Extracted audio
                  </p>
                  <p className="mt-1 break-all font-mono text-xs text-zinc-300">
                    {project.extracted_audio_path}
                  </p>
                  {project.extracted_audio_duration_seconds != null ? (
                    <p className="mt-2 text-xs text-zinc-500">
                      Duration:{" "}
                      {formatDuration(project.extracted_audio_duration_seconds)}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {project.last_error ? (
                <p className="text-xs text-red-300">Last error: {project.last_error}</p>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader title="Processing Activity Log" />
        <CardContent className="p-0">
          {project.activity_log.length === 0 ? (
            <p className="p-5 text-sm text-zinc-500">No activity yet.</p>
          ) : (
            <ul className="divide-y divide-zinc-800/60">
              {[...project.activity_log].reverse().map((entry, index) => (
                <li key={`${entry.timestamp}-${index}`} className="px-5 py-4">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <p
                      className={cn(
                        "text-sm",
                        entry.level === "error" ? "text-red-300" : "text-zinc-300",
                      )}
                    >
                      {entry.message}
                    </p>
                    <time className="text-xs text-zinc-600">
                      {new Date(entry.timestamp).toLocaleString()}
                    </time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
