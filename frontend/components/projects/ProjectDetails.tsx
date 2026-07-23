"use client";

import {
  analyzeProject,
  deleteProjectClip,
  deleteProjectClipCaptions,
  exportProjectClip,
  favoriteProjectClip,
  extractProjectAudio,
  fetchProject,
  fetchProjectAnalysis,
  fetchProjectClipCandidates,
  fetchProjectClipCaptions,
  fetchProjectClipExports,
  fetchProjectTranscript,
  generateProjectClipCaptions,
  getProjectVideoUrl,
  inspectProject,
  renameProjectClip,
  renderProjectClipCaptions,
  resetProjectClipCaptionStyle,
  selectProjectClips,
  trimProjectClip,
  transcribeProject,
  updateProjectClipCaptionStyle,
  updateProjectClipCaptions,
  type AnalysisDocument,
  type ApiError,
  type ClipCandidate,
  type ClipCandidatesDocument,
  type ClipCaptionsResponse,
  type ExportClipRequest,
  type ExportClipResponse,
  type Project,
  type SegmentAnalysis,
  type TranscriptDocument,
} from "@/lib/api/projects";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import {
  ClipCandidatesPanel,
  ClipCandidatesState,
} from "@/components/projects/ClipCandidatesPanel";
import {
  ExportedClipsPanel,
  ExportedClipsSummary,
} from "@/components/projects/ExportedClipsPanel";
import { ClipEditor } from "@/components/projects/ClipEditor";
import {
  buildCaptionUpdatePayload,
  CaptionEditor,
} from "@/components/projects/CaptionEditor";
import {
  TimelineAnalysisPanel,
  TimelineAnalysisState,
} from "@/components/projects/TimelineAnalysisPanel";
import {
  TranscriptViewer,
  TranscriptViewerState,
} from "@/components/projects/TranscriptViewer";
import { cn, formatDuration, formatFileSize } from "@/lib/utils";
import { defaultAnalysisFilters, type AnalysisFilters } from "@/lib/analysis-filters";
import {
  defaultClipCandidateFilters,
  type ClipCandidateFilters,
} from "@/lib/clip-candidate-filters";
import {
  buildExportClipRequest,
  buildExportClipRequestFromSegment,
  buildExportKeyFromCandidate,
  buildExportKeyFromSegment,
  buildExportedStateFromClips,
  clearCandidateExportedState,
  isCandidateExported,
  isCandidateExporting,
  mergeExportedClips,
  mergeLoadedExports,
  removeExportedClip,
  updateExportedClip,
  type CandidateExportState,
} from "@/lib/clip-export";
import {
  AlertCircle,
  AudioLines,
  CheckCircle2,
  Loader2,
  ScanSearch,
  Scissors,
  Sparkles,
  Subtitles,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

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

function formatFrameRate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value.toFixed(2)} fps`;
}

export function ProjectDetails({ projectId }: ProjectDetailsProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [inspectState, setInspectState] = useState<ActionState>("idle");
  const [extractState, setExtractState] = useState<ActionState>("idle");
  const [transcribeState, setTranscribeState] = useState<ActionState>("idle");
  const [analyzeState, setAnalyzeState] = useState<ActionState>("idle");
  const [selectClipsState, setSelectClipsState] = useState<ActionState>("idle");
  const [transcript, setTranscript] = useState<TranscriptDocument | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisDocument | null>(null);
  const [clipCandidates, setClipCandidates] = useState<ClipCandidatesDocument | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [clipCandidatesLoading, setClipCandidatesLoading] = useState(false);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [clipCandidatesError, setClipCandidatesError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [analysisFilters, setAnalysisFilters] = useState<AnalysisFilters>(defaultAnalysisFilters);
  const [clipCandidateFilters, setClipCandidateFilters] = useState<ClipCandidateFilters>(
    defaultClipCandidateFilters,
  );
  const [exportedClips, setExportedClips] = useState<ExportClipResponse[]>([]);
  const [exportedClipsLoading, setExportedClipsLoading] = useState(false);
  const [exportedClipsError, setExportedClipsError] = useState<string | null>(null);
  const [editingClip, setEditingClip] = useState<ExportClipResponse | null>(null);
  const [trimSaving, setTrimSaving] = useState(false);
  const [trimError, setTrimError] = useState<string | null>(null);
  const [captionClip, setCaptionClip] = useState<ExportClipResponse | null>(null);
  const [clipCaptions, setClipCaptions] = useState<ClipCaptionsResponse | null>(null);
  const [captionsLoading, setCaptionsLoading] = useState(false);
  const [captionsGenerating, setCaptionsGenerating] = useState(false);
  const [captionsSaving, setCaptionsSaving] = useState(false);
  const [captionStyleSaving, setCaptionStyleSaving] = useState(false);
  const [captionStyleResetting, setCaptionStyleResetting] = useState(false);
  const [captionsRendering, setCaptionsRendering] = useState(false);
  const [captionRenderSuccess, setCaptionRenderSuccess] = useState<string | null>(null);
  const [captionsResetting, setCaptionsResetting] = useState(false);
  const [captionsError, setCaptionsError] = useState<string | null>(null);
  const [exportStates, setExportStates] = useState<Record<string, CandidateExportState>>({});
  const [exportedCandidateIds, setExportedCandidateIds] = useState<Set<string>>(
    () => new Set(),
  );
  const loadExportedClipsRequestIdRef = useRef(0);
  const captionsRenderInFlightRef = useRef(false);
  const pendingDeletedClipIdsRef = useRef<Set<string>>(new Set());
  const exportStatesRef = useRef(exportStates);

  useEffect(() => {
    exportStatesRef.current = exportStates;
  }, [exportStates]);

  const isActionLoading =
    inspectState === "loading" ||
    extractState === "loading" ||
    transcribeState === "loading" ||
    analyzeState === "loading" ||
    selectClipsState === "loading";

  const loadTranscript = useCallback(async () => {
    setTranscriptLoading(true);
    setTranscriptError(null);

    try {
      const data = await fetchProjectTranscript(projectId);
      setTranscript(data);
      return data;
    } catch (error) {
      const status =
        error && typeof error === "object" && "status" in error
          ? (error as ApiError).status
          : undefined;
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to load transcript.";

      setTranscript(null);
      if (status !== 404) {
        setTranscriptError(message);
      }
      return null;
    } finally {
      setTranscriptLoading(false);
    }
  }, [projectId]);

  const loadAnalysis = useCallback(async () => {
    setAnalysisLoading(true);
    setAnalysisError(null);

    try {
      const data = await fetchProjectAnalysis(projectId);
      setAnalysis(data);
      return data;
    } catch (error) {
      const status =
        error && typeof error === "object" && "status" in error
          ? (error as ApiError).status
          : undefined;
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to load timeline analysis.";

      setAnalysis(null);
      if (status !== 404) {
        setAnalysisError(message);
      }
      return null;
    } finally {
      setAnalysisLoading(false);
    }
  }, [projectId]);

  const loadClipCandidates = useCallback(async () => {
    setClipCandidatesLoading(true);
    setClipCandidatesError(null);

    try {
      const data = await fetchProjectClipCandidates(projectId);
      setClipCandidates(data);
      return data;
    } catch (error) {
      const status =
        error && typeof error === "object" && "status" in error
          ? (error as ApiError).status
          : undefined;
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to load clip candidates.";

      setClipCandidates(null);
      if (status !== 404) {
        setClipCandidatesError(message);
      }
      return null;
    } finally {
      setClipCandidatesLoading(false);
    }
  }, [projectId]);

  const loadExportedClips = useCallback(async () => {
    const requestId = ++loadExportedClipsRequestIdRef.current;
    setExportedClipsLoading(true);
    setExportedClipsError(null);

    try {
      const data = await fetchProjectClipExports(projectId);
      if (requestId !== loadExportedClipsRequestIdRef.current) {
        return data.exports;
      }

      const restored = buildExportedStateFromClips(data.exports);

      for (const clipId of pendingDeletedClipIdsRef.current) {
        if (!data.exports.some((clip) => clip.clip_id === clipId)) {
          pendingDeletedClipIdsRef.current.delete(clipId);
        }
      }

      setExportedClips((currentClips) => {
        const merged = mergeLoadedExports(data.exports, currentClips);
        return merged.filter(
          (clip) => !pendingDeletedClipIdsRef.current.has(clip.clip_id),
        );
      });
      setExportedCandidateIds((currentIds) => {
        const next = new Set(restored.exportedCandidateIds);
        for (const candidateId of currentIds) {
          if (exportStatesRef.current[candidateId]?.status === "exporting") {
            next.add(candidateId);
          }
        }
        return next;
      });
      setExportStates((currentStates) => {
        const next = { ...restored.exportStates };
        for (const [candidateId, state] of Object.entries(currentStates)) {
          if (state.status === "exporting" || state.status === "failed") {
            next[candidateId] = state;
          }
        }
        return next;
      });

      return data.exports;
    } catch (error) {
      if (requestId !== loadExportedClipsRequestIdRef.current) {
        return null;
      }

      const status =
        error && typeof error === "object" && "status" in error
          ? (error as ApiError).status
          : undefined;
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to load exported clips.";

      setExportedClipsError(
        status === 404
          ? "Saved exports could not be loaded because GET /api/projects/{project_id}/clips/exports is unavailable on the backend. Restart the backend server to pick up the export list endpoint, then refresh."
          : message,
      );
      return null;
    } finally {
      if (requestId === loadExportedClipsRequestIdRef.current) {
        setExportedClipsLoading(false);
      }
    }
  }, [projectId]);

  const applyProjectState = useCallback(
    async (data: Project) => {
      setProject(data);
      await loadExportedClips();
      if (data.transcription_status === "completed") {
        await loadTranscript();
      } else {
        setTranscript(null);
        setTranscriptError(null);
      }

      if (data.analysis_status === "completed") {
        await loadAnalysis();
      } else {
        setAnalysis(null);
        setAnalysisError(null);
      }

      if (data.clip_selection_status === "completed") {
        await loadClipCandidates();
      } else {
        setClipCandidates(null);
        setClipCandidatesError(null);
      }
    },
    [loadAnalysis, loadClipCandidates, loadExportedClips, loadTranscript],
  );

  const seekVideoTo = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    void video.play().catch(() => {
      // Autoplay may be blocked until the user interacts with the page.
    });
  }, []);

  const handleExport = useCallback(
    async (exportKey: string, request: ExportClipRequest) => {
      if (
        isCandidateExported(exportKey, exportedCandidateIds, exportStates) ||
        isCandidateExporting(exportKey, exportStates)
      ) {
        return;
      }

      setExportStates((current) => ({
        ...current,
        [exportKey]: { status: "exporting" },
      }));

      try {
        const response = await exportProjectClip(projectId, request);

        setExportedClips((current) => mergeExportedClips([response], current));
        setExportedCandidateIds((current) => new Set(current).add(exportKey));
        setExportStates((current) => ({
          ...current,
          [exportKey]: { status: "completed" },
        }));
      } catch (error) {
        const message =
          error && typeof error === "object" && "message" in error
            ? String((error as ApiError).message)
            : "Clip export failed.";

        setExportStates((current) => ({
          ...current,
          [exportKey]: { status: "failed", error: message },
        }));
      }
    },
    [exportStates, exportedCandidateIds, projectId],
  );

  const handleExportSegment = useCallback(
    (segment: SegmentAnalysis) => {
      void handleExport(
        buildExportKeyFromSegment(segment),
        buildExportClipRequestFromSegment(segment),
      );
    },
    [handleExport],
  );

  const handleExportClip = useCallback(
    (candidate: ClipCandidate) => {
      void handleExport(
        buildExportKeyFromCandidate(candidate),
        buildExportClipRequest(candidate),
      );
    },
    [handleExport],
  );

  const handleRenameExportedClip = useCallback(
    async (clipId: string, clipName: string) => {
      const updated = await renameProjectClip(projectId, clipId, { clip_name: clipName });
      setExportedClips((current) => updateExportedClip(current, updated));
    },
    [projectId],
  );

  const handleFavoriteExportedClip = useCallback(
    async (clipId: string, isFavorite: boolean) => {
      const updated = await favoriteProjectClip(projectId, clipId, { is_favorite: isFavorite });
      setExportedClips((current) => updateExportedClip(current, updated));
    },
    [projectId],
  );

  const handleDeleteExportedClip = useCallback(
    async (clipId: string) => {
      const clipToDelete = exportedClips.find((clip) => clip.clip_id === clipId);
      await deleteProjectClip(projectId, clipId);

      pendingDeletedClipIdsRef.current.add(clipId);
      loadExportedClipsRequestIdRef.current += 1;
      setExportedClips((current) => removeExportedClip(current, clipId));

      if (clipToDelete?.candidate_id) {
        const cleared = clearCandidateExportedState(
          clipToDelete.candidate_id,
          exportedCandidateIds,
          exportStates,
        );
        setExportedCandidateIds(cleared.exportedCandidateIds);
        setExportStates(cleared.exportStates);
      }
    },
    [exportStates, exportedCandidateIds, exportedClips, projectId],
  );

  const handleEditExportedClip = useCallback((clip: ExportClipResponse) => {
    setTrimError(null);
    setEditingClip(clip);
  }, []);

  const handleCloseClipEditor = useCallback(() => {
    if (trimSaving) {
      return;
    }
    setEditingClip(null);
    setTrimError(null);
  }, [trimSaving]);

  const loadClipCaptions = useCallback(
    async (clipId: string) => {
      setCaptionsLoading(true);
      setCaptionsError(null);

      try {
        const captions = await fetchProjectClipCaptions(projectId, clipId);
        setClipCaptions(captions);
      } catch (error) {
        const status =
          error && typeof error === "object" && "status" in error
            ? Number((error as ApiError).status)
            : undefined;
        if (status === 404) {
          setClipCaptions(null);
        } else {
          const message =
            error && typeof error === "object" && "message" in error
              ? String((error as ApiError).message)
              : "Unable to load captions.";
          setCaptionsError(message);
          setClipCaptions(null);
        }
      } finally {
        setCaptionsLoading(false);
      }
    },
    [projectId],
  );

  const handleOpenCaptionsEditor = useCallback(
    (clip: ExportClipResponse) => {
      setCaptionClip(clip);
      setCaptionsError(null);
      void loadClipCaptions(clip.clip_id);
    },
    [loadClipCaptions],
  );

  const handleCloseCaptionsEditor = useCallback(() => {
    if (
      captionsGenerating ||
      captionsSaving ||
      captionStyleSaving ||
      captionStyleResetting ||
      captionsRendering ||
      captionsResetting
    ) {
      return;
    }
    setCaptionClip(null);
    setClipCaptions(null);
    setCaptionsError(null);
    setCaptionRenderSuccess(null);
  }, [
    captionStyleResetting,
    captionStyleSaving,
    captionsGenerating,
    captionsRendering,
    captionsResetting,
    captionsSaving,
  ]);

  const handleGenerateCaptions = useCallback(async () => {
    if (!captionClip) {
      return;
    }

    setCaptionsGenerating(true);
    setCaptionsError(null);

    try {
      const captions = await generateProjectClipCaptions(projectId, captionClip.clip_id);
      setClipCaptions(captions);
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to generate captions.";
      setCaptionsError(message);
    } finally {
      setCaptionsGenerating(false);
    }
  }, [captionClip, projectId]);

  const handleSaveCaptions = useCallback(
    async (segments: ClipCaptionsResponse["segments"]) => {
      if (!captionClip) {
        return;
      }

      setCaptionsSaving(true);
      setCaptionsError(null);

      try {
        const updated = await updateProjectClipCaptions(
          projectId,
          captionClip.clip_id,
          { segments: buildCaptionUpdatePayload(segments) },
        );
        setClipCaptions(updated);
      } catch (error) {
        const message =
          error && typeof error === "object" && "message" in error
            ? String((error as ApiError).message)
            : "Unable to save captions.";
        setCaptionsError(message);
        throw error;
      } finally {
        setCaptionsSaving(false);
      }
    },
    [captionClip, projectId],
  );

  const handleSaveCaptionStyle = useCallback(
    async (style: ClipCaptionsResponse["style"]) => {
      if (!captionClip) {
        return;
      }

      setCaptionStyleSaving(true);
      setCaptionsError(null);

      try {
        const updated = await updateProjectClipCaptionStyle(
          projectId,
          captionClip.clip_id,
          { style },
        );
        setClipCaptions(updated);
      } catch (error) {
        const message =
          error && typeof error === "object" && "message" in error
            ? String((error as ApiError).message)
            : "Unable to save caption style.";
        setCaptionsError(message);
        throw error;
      } finally {
        setCaptionStyleSaving(false);
      }
    },
    [captionClip, projectId],
  );

  const handleResetCaptionStyle = useCallback(async () => {
    if (!captionClip) {
      return;
    }

    setCaptionStyleResetting(true);
    setCaptionsError(null);

    try {
      const updated = await resetProjectClipCaptionStyle(projectId, captionClip.clip_id);
      setClipCaptions(updated);
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to reset caption style.";
      setCaptionsError(message);
    } finally {
      setCaptionStyleResetting(false);
    }
  }, [captionClip, projectId]);

  const handleRenderCaptions = useCallback(async () => {
    if (!captionClip || captionsRenderInFlightRef.current) {
      return;
    }

    captionsRenderInFlightRef.current = true;
    setCaptionsRendering(true);
    setCaptionsError(null);
    setCaptionRenderSuccess(null);

    try {
      const rendered = await renderProjectClipCaptions(projectId, captionClip.clip_id);
      setExportedClips((current) => mergeExportedClips([rendered], current));
      setCaptionRenderSuccess(
        `Captioned export ready: ${rendered.clip_name ?? rendered.filename}. Find it in Exported Clips.`,
      );
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to render captioned export.";
      setCaptionsError(message);
      throw error;
    } finally {
      captionsRenderInFlightRef.current = false;
      setCaptionsRendering(false);
    }
  }, [captionClip, projectId]);

  const handleResetCaptions = useCallback(async () => {
    if (!captionClip) {
      return;
    }

    setCaptionsResetting(true);
    setCaptionsError(null);

    try {
      await deleteProjectClipCaptions(projectId, captionClip.clip_id);
      setClipCaptions(null);
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to reset captions.";
      setCaptionsError(message);
    } finally {
      setCaptionsResetting(false);
    }
  }, [captionClip, projectId]);

  const handleSaveTrimmedClip = useCallback(
    async ({
      startTime,
      endTime,
      clipName,
    }: {
      startTime: number;
      endTime: number;
      clipName: string;
    }) => {
      if (!editingClip) {
        return;
      }

      setTrimSaving(true);
      setTrimError(null);

      try {
        const trimmed = await trimProjectClip(projectId, editingClip.clip_id, {
          start_time: startTime,
          end_time: endTime,
          clip_name: clipName,
        });
        setExportedClips((current) => mergeExportedClips([trimmed], current));
        setEditingClip(null);
      } catch (error) {
        const message =
          error && typeof error === "object" && "message" in error
            ? String((error as ApiError).message)
            : "Unable to save trimmed clip.";
        setTrimError(message);
      } finally {
        setTrimSaving(false);
      }
    },
    [editingClip, projectId],
  );

  const loadProject = useCallback(async () => {
    setPageError(null);

    try {
      const data = await fetchProject(projectId);
      await applyProjectState(data);
      return data;
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Unable to load project.";
      setPageError(message);
      setProject(null);
      setTranscript(null);
      setAnalysis(null);
      setClipCandidates(null);
      return null;
    }
  }, [applyProjectState, projectId]);

  useEffect(() => {
    let cancelled = false;

    async function initializeProject() {
      setLoading(true);
      setPageError(null);

      try {
        const data = await fetchProject(projectId);
        if (!cancelled) {
          await applyProjectState(data);
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
  }, [applyProjectState, projectId]);

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

  const handleTranscribe = async () => {
    setTranscribeState("loading");
    setActionError(null);
    setTranscriptError(null);

    try {
      await transcribeProject(projectId);
      setTranscribeState("success");
      await refreshProject();
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Transcription failed.";
      setActionError(message);
      setTranscribeState("error");
      await refreshProject();
    }
  };

  const handleAnalyze = async () => {
    setAnalyzeState("loading");
    setActionError(null);
    setAnalysisError(null);

    try {
      await analyzeProject(projectId);
      setAnalyzeState("success");
      await refreshProject();
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Timeline analysis failed.";
      setActionError(message);
      setAnalyzeState("error");
      if (
        /provider|analysis_api_key|openai|unavailable/i.test(message)
      ) {
        setAnalysisError(message);
      }
      await refreshProject();
    }
  };

  const handleSelectClips = async () => {
    setSelectClipsState("loading");
    setActionError(null);
    setClipCandidatesError(null);

    try {
      await selectProjectClips(projectId);
      setSelectClipsState("success");
      await refreshProject();
    } catch (error) {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as ApiError).message)
          : "Clip selection failed.";
      setActionError(message);
      setSelectClipsState("error");
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
            <Badge variant={statusVariant(project.transcription_status)}>
              Transcript: {project.transcription_status}
            </Badge>
            <Badge variant={statusVariant(project.analysis_status)}>
              Analysis: {project.analysis_status}
            </Badge>
            <Badge variant={statusVariant(project.clip_selection_status)}>
              Clip selection: {project.clip_selection_status}
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
            disabled={isActionLoading}
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
            variant="secondary"
            onClick={handleExtractAudio}
            disabled={isActionLoading}
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
          <Button
            onClick={handleTranscribe}
            disabled={isActionLoading || project.audio_extraction_status !== "completed"}
            icon={
              transcribeState === "loading" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Subtitles className="h-4 w-4" />
              )
            }
          >
            {transcribeState === "loading" ? "Transcribing..." : "Transcribe"}
          </Button>
          <Button
            variant="secondary"
            onClick={handleAnalyze}
            disabled={isActionLoading || project.transcription_status !== "completed"}
            icon={
              analyzeState === "loading" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )
            }
          >
            {analyzeState === "loading" ? "Analyzing..." : "Analyze"}
          </Button>
          <Button
            onClick={handleSelectClips}
            disabled={isActionLoading || project.analysis_status !== "completed"}
            icon={
              selectClipsState === "loading" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Scissors className="h-4 w-4" />
              )
            }
          >
            {selectClipsState === "loading" ? "Selecting..." : "Select Clips"}
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

      {(inspectState === "success" ||
        extractState === "success" ||
        transcribeState === "success" ||
        analyzeState === "success" ||
        selectClipsState === "success") &&
      !actionError ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
            <p className="text-sm text-emerald-300">
              {selectClipsState === "success"
                ? "Clip selection completed. Proposed candidates loaded below."
                : analyzeState === "success"
                  ? "Timeline analysis completed. Results loaded below."
                  : transcribeState === "success"
                    ? "Transcription completed. Transcript loaded below."
                    : extractState === "success"
                      ? "Audio extraction completed. Project state refreshed."
                      : "Video inspection completed. Project state refreshed."}
            </p>
          </CardContent>
        </Card>
      ) : null}

      {selectClipsState === "loading" ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-300" />
            <div>
              <p className="text-sm font-medium text-zinc-200">Clip selection in progress</p>
              <p className="mt-1 text-sm text-zinc-500">
                Grouping strong transcript segments into ranked proposed clip candidates.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {analyzeState === "loading" ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-300" />
            <div>
              <p className="text-sm font-medium text-zinc-200">Timeline analysis in progress</p>
              <p className="mt-1 text-sm text-zinc-500">
                Scoring transcript segments in batches for clip candidate selection.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {transcribeState === "loading" ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-300" />
            <div>
              <p className="text-sm font-medium text-zinc-200">Transcription in progress</p>
              <p className="mt-1 text-sm text-zinc-500">
                Running faster-whisper on the extracted audio. This may take a minute for longer
                clips.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title="Video Preview" description="Uploaded source file" />
          <CardContent>
            <div className="overflow-hidden rounded-lg border border-zinc-800 bg-black">
              <video
                ref={videoRef}
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
              <div className="flex items-center justify-between gap-4">
                <span className="text-zinc-500">Transcription</span>
                <Badge variant={statusVariant(project.transcription_status)}>
                  {project.transcription_status}
                </Badge>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-zinc-500">Timeline analysis</span>
                <Badge variant={statusVariant(project.analysis_status)}>
                  {project.analysis_status}
                </Badge>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-zinc-500">Clip selection</span>
                <Badge variant={statusVariant(project.clip_selection_status)}>
                  {project.clip_selection_status}
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
              {project.transcript_path ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                  <p className="text-xs uppercase tracking-wider text-zinc-500">Transcript</p>
                  <p className="mt-1 break-all font-mono text-xs text-zinc-300">
                    {project.transcript_path}
                  </p>
                  {project.detected_language ? (
                    <p className="mt-2 text-xs text-zinc-500">
                      Language: {project.detected_language.toUpperCase()}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {project.analysis_path ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                  <p className="text-xs uppercase tracking-wider text-zinc-500">Analysis</p>
                  <p className="mt-1 break-all font-mono text-xs text-zinc-300">
                    {project.analysis_path}
                  </p>
                  {project.analysis_provider ? (
                    <p className="mt-2 text-xs text-zinc-500">
                      Provider: {project.analysis_provider}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {project.clip_candidates_path ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                  <p className="text-xs uppercase tracking-wider text-zinc-500">
                    Clip candidates
                  </p>
                  <p className="mt-1 break-all font-mono text-xs text-zinc-300">
                    {project.clip_candidates_path}
                  </p>
                  {project.clip_candidate_count != null ? (
                    <p className="mt-2 text-xs text-zinc-500">
                      Proposed clips: {project.clip_candidate_count}
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
        <CardHeader
          title="Transcript"
          description={
            project.transcription_status === "completed"
              ? "Segment-level transcript with clickable timestamps"
              : "Run transcription after audio extraction to generate a transcript"
          }
        />
        <CardContent>
          {transcript ? (
            <TranscriptViewer
              transcript={transcript}
              analysis={analysis}
              filters={analysisFilters}
              onFiltersChange={analysis ? setAnalysisFilters : undefined}
              onSeek={seekVideoTo}
            />
          ) : (
            <TranscriptViewerState
              loading={transcriptLoading || transcribeState === "loading"}
              error={transcriptError}
            />
          )}
          {!transcript &&
          !transcriptLoading &&
          transcribeState !== "loading" &&
          !transcriptError &&
          project.transcription_status !== "completed" ? (
            <p className="text-sm text-zinc-500">
              No transcript yet. Extract audio, then click Transcribe to generate one.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Timeline Analysis"
          description={
            project.analysis_status === "completed"
              ? "Segment scoring and clip candidates — export directly from highlighted segments"
              : "Analyze the completed transcript to score clip candidates"
          }
        />
        <CardContent>
          {analysis ? (
            <TimelineAnalysisPanel
              analysis={analysis}
              filters={analysisFilters}
              onSeek={seekVideoTo}
              exportStates={exportStates}
              exportedCandidateIds={exportedCandidateIds}
              onExportSegment={handleExportSegment}
            />
          ) : (
            <TimelineAnalysisState
              loading={analysisLoading || analyzeState === "loading"}
              error={analysisError}
              unavailableProvider={
                analyzeState === "error" &&
                analysisError &&
                /provider|analysis_api_key|openai|unavailable/i.test(analysisError)
                  ? analysisError
                  : null
              }
            />
          )}
          {!analysis &&
          !analysisLoading &&
          analyzeState !== "loading" &&
          !analysisError &&
          project.analysis_status !== "completed" ? (
            <p className="text-sm text-zinc-500">
              No timeline analysis yet. Complete transcription, then click Analyze.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Clip Candidates"
          description={
            project.clip_selection_status === "completed"
              ? "Ranked proposed clip ranges from Select Clips — not rendered video files"
              : "Optional ranked clip selection after analysis. You can export directly from Timeline Analysis above."
          }
        />
        <CardContent>
          {clipCandidates ? (
            <ClipCandidatesPanel
              clipCandidates={clipCandidates}
              filters={clipCandidateFilters}
              onFiltersChange={setClipCandidateFilters}
              onSeek={seekVideoTo}
              exportStates={exportStates}
              exportedCandidateIds={exportedCandidateIds}
              onExport={handleExportClip}
            />
          ) : (
            <ClipCandidatesState
              loading={clipCandidatesLoading || selectClipsState === "loading"}
              error={clipCandidatesError}
            />
          )}
          {!clipCandidates &&
          !clipCandidatesLoading &&
          selectClipsState !== "loading" &&
          !clipCandidatesError &&
          project.clip_selection_status !== "completed" ? (
            <p className="text-sm text-zinc-500">
              No ranked clip candidates yet. Export directly from Timeline Analysis above, or click
              Select Clips to generate ranked ranges.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Exported Clips"
          description="Saved MP4 files exported from clip candidates"
          action={<ExportedClipsSummary count={exportedClips.length} />}
        />
        <CardContent>
          <ExportedClipsPanel
            exportedClips={exportedClips}
            loading={exportedClipsLoading}
            error={exportedClipsError}
            onRename={handleRenameExportedClip}
            onDelete={handleDeleteExportedClip}
            onFavorite={handleFavoriteExportedClip}
            onEdit={handleEditExportedClip}
            onCaptions={handleOpenCaptionsEditor}
          />
        </CardContent>
      </Card>

      {captionClip ? (
        <CaptionEditor
          key={`${captionClip.clip_id}-${clipCaptions?.updated_at ?? "empty"}-${captionsLoading ? "loading" : "ready"}`}
          clip={captionClip}
          captions={clipCaptions}
          loading={captionsLoading}
          generating={captionsGenerating}
          saving={captionsSaving}
          styleSaving={captionStyleSaving}
          styleResetting={captionStyleResetting}
          rendering={captionsRendering}
          resetting={captionsResetting}
          error={captionsError}
          renderSuccess={captionRenderSuccess}
          onGenerate={handleGenerateCaptions}
          onSave={handleSaveCaptions}
          onSaveStyle={handleSaveCaptionStyle}
          onResetStyle={handleResetCaptionStyle}
          onRender={handleRenderCaptions}
          onReset={handleResetCaptions}
          onClose={handleCloseCaptionsEditor}
        />
      ) : null}

      {editingClip ? (
        <ClipEditor
          clip={editingClip}
          sourceVideoUrl={getProjectVideoUrl(projectId)}
          frameRate={project.video_metadata?.frame_rate ?? null}
          saving={trimSaving}
          error={trimError}
          onSave={handleSaveTrimmedClip}
          onClose={handleCloseClipEditor}
        />
      ) : null}

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
