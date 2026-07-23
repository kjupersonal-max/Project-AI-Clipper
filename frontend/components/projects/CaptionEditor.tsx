"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CaptionPresetPanel } from "@/components/projects/CaptionPresetPanel";
import { CaptionPreviewOverlay } from "@/components/projects/CaptionPreviewOverlay";
import { CaptionStylePanel, cloneCaptionStyle } from "@/components/projects/CaptionStylePanel";
import type { ClipCaptionsResponse, ExportClipResponse } from "@/lib/api/projects";
import { getProjectClipMediaUrl, resolveMediaUrl } from "@/lib/api/projects";
import { createDefaultCaptionStyle, type CaptionStyle } from "@/lib/caption-style";
import {
  buildCaptionUpdatePayload,
  cloneCaptionSegments,
  findActiveCaption,
  formatCaptionTimestamp,
  parseCaptionTimestamp,
  sortCaptionSegments,
  validateCaptionSegments,
  type CaptionSegment,
} from "@/lib/clip-captions";
import { getClipDisplayName } from "@/lib/exported-clips-library";
import { cn, formatDuration } from "@/lib/utils";
import {
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  Video,
  X,
} from "lucide-react";

type CaptionEditorProps = {
  clip: ExportClipResponse;
  captions: ClipCaptionsResponse | null;
  loading?: boolean;
  generating?: boolean;
  saving?: boolean;
  rendering?: boolean;
  styleSaving?: boolean;
  styleResetting?: boolean;
  resetting?: boolean;
  error?: string | null;
  renderSuccess?: string | null;
  onGenerate: () => Promise<void>;
  onSave: (segments: CaptionSegment[]) => Promise<void>;
  onSaveStyle: (style: CaptionStyle) => Promise<void>;
  onResetStyle: () => Promise<void>;
  onRender: () => Promise<void>;
  onReset: () => Promise<void>;
  onClose: () => void;
};

function stylesEqual(left: CaptionStyle, right: CaptionStyle): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function CaptionEditor({
  clip,
  captions,
  loading = false,
  generating = false,
  saving = false,
  rendering = false,
  styleSaving = false,
  styleResetting = false,
  resetting = false,
  error = null,
  renderSuccess = null,
  onGenerate,
  onSave,
  onSaveStyle,
  onResetStyle,
  onRender,
  onReset,
  onClose,
}: CaptionEditorProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const renderInFlightRef = useRef(false);
  const currentTimeRef = useRef(0);
  const [segments, setSegments] = useState<CaptionSegment[]>(() =>
    captions ? cloneCaptionSegments(sortCaptionSegments(captions.segments)) : [],
  );
  const [captionStyle, setCaptionStyle] = useState<CaptionStyle>(() =>
    captions?.style ? cloneCaptionStyle(captions.style) : createDefaultCaptionStyle(),
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    () => captions?.segments[0]?.id ?? null,
  );
  const [playbackTime, setPlaybackTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [segmentsDirty, setSegmentsDirty] = useState(false);
  const [styleDirty, setStyleDirty] = useState(false);
  const [showSafeAreaGuides, setShowSafeAreaGuides] = useState(
    () => (captions?.style ?? createDefaultCaptionStyle()).safe_area_mode !== "none",
  );
  const [editorTab, setEditorTab] = useState<"segments" | "style">("segments");

  const clipTitle = getClipDisplayName(clip);
  const mediaUrl = resolveMediaUrl(getProjectClipMediaUrl(clip.project_id, clip.clip_id));
  const isBusy =
    loading || generating || saving || rendering || styleSaving || styleResetting || resetting;

  const activeCaption = useMemo(
    () => findActiveCaption(segments, playbackTime),
    [playbackTime, segments],
  );

  const validationError = useMemo(
    () => validateCaptionSegments(segments, clip.duration),
    [clip.duration, segments],
  );

  const canRender =
    Boolean(captions) &&
    segments.length > 0 &&
    !segmentsDirty &&
    !styleDirty &&
    !validationError;

  useEffect(() => {
    if (!rendering) {
      renderInFlightRef.current = false;
    }
  }, [rendering]);

  const handleRender = useCallback(async () => {
    if (renderInFlightRef.current || isBusy || !canRender) {
      return;
    }

    renderInFlightRef.current = true;
    try {
      await onRender();
    } catch {
      if (!rendering) {
        renderInFlightRef.current = false;
      }
    }
  }, [canRender, isBusy, onRender, rendering]);

  const togglePlayback = useCallback(async () => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    if (video.paused) {
      await video.play();
    } else {
      video.pause();
    }
  }, []);

  const seekTo = useCallback(
    (time: number) => {
      const video = videoRef.current;
      const clamped = Math.max(0, Math.min(time, clip.duration));
      if (video) {
        video.currentTime = clamped;
      }
      currentTimeRef.current = clamped;
      setPlaybackTime(clamped);
    },
    [clip.duration],
  );

  const updateSegment = useCallback(
    (segmentId: string, patch: Partial<Pick<CaptionSegment, "text" | "start" | "end">>) => {
      setSegments((current) =>
        current.map((segment) =>
          segment.id === segmentId ? { ...segment, ...patch } : segment,
        ),
      );
      setSegmentsDirty(true);
      setLocalError(null);
    },
    [],
  );

  const handleStyleChange = useCallback(
    (nextStyle: CaptionStyle) => {
      setCaptionStyle(nextStyle);
      const persistedStyle = captions?.style ?? createDefaultCaptionStyle();
      setStyleDirty(!stylesEqual(nextStyle, persistedStyle));
      if (nextStyle.safe_area_mode === "none") {
        setShowSafeAreaGuides(false);
      }
    },
    [captions?.style],
  );

  const handleSave = useCallback(async () => {
    if (validationError) {
      setLocalError(validationError);
      return;
    }

    setLocalError(null);
    await onSave(segments);
    setSegmentsDirty(false);
  }, [onSave, segments, validationError]);

  const handleSaveStyle = useCallback(async () => {
    setLocalError(null);
    await onSaveStyle(captionStyle);
    setStyleDirty(false);
  }, [captionStyle, onSaveStyle]);

  const handleResetStyle = useCallback(async () => {
    setLocalError(null);
    await onResetStyle();
    setStyleDirty(false);
  }, [onResetStyle]);

  const handleReset = useCallback(async () => {
    if (!confirmReset) {
      setConfirmReset(true);
      return;
    }

    setConfirmReset(false);
    await onReset();
    setSegmentsDirty(false);
    setStyleDirty(false);
  }, [confirmReset, onReset]);

  useEffect(() => {
    const videoElement = videoRef.current;
    if (!videoElement) {
      return;
    }
    const element: HTMLVideoElement = videoElement;

    function handleTimeUpdate() {
      currentTimeRef.current = element.currentTime;
      setPlaybackTime((previous) => {
        const next = element.currentTime;
        const active = findActiveCaption(segments, next);
        const previousActive = findActiveCaption(segments, previous);
        if (active?.id !== previousActive?.id || Math.abs(next - previous) >= 0.1) {
          return next;
        }
        return previous;
      });
    }

    function handlePlay() {
      setIsPlaying(true);
    }

    function handlePause() {
      setIsPlaying(false);
    }

    element.addEventListener("timeupdate", handleTimeUpdate);
    element.addEventListener("seeked", handleTimeUpdate);
    element.addEventListener("play", handlePlay);
    element.addEventListener("pause", handlePause);
    return () => {
      element.removeEventListener("timeupdate", handleTimeUpdate);
      element.removeEventListener("seeked", handleTimeUpdate);
      element.removeEventListener("play", handlePlay);
      element.removeEventListener("pause", handlePause);
    };
  }, [segments]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !isBusy) {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isBusy, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Captions for ${clipTitle}`}
        className="flex max-h-[92vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Captions: {clipTitle}</h2>
            <p className="text-sm text-zinc-500">
              Clip duration {formatDuration(clip.duration)} · {segments.length} caption
              {segments.length === 1 ? "" : "s"}
              {segmentsDirty || styleDirty ? " · Unsaved changes" : ""}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close caption editor"
            disabled={isBusy}
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-100 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid flex-1 gap-5 overflow-y-auto px-5 py-5 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="space-y-4">
            <div className="relative overflow-hidden rounded-lg border border-zinc-800 bg-black">
              <video
                ref={videoRef}
                src={mediaUrl}
                className="aspect-video w-full bg-black"
                playsInline
                preload="metadata"
              />
              {segments.length > 0 ? (
                <CaptionPreviewOverlay
                  videoRef={videoRef}
                  segments={segments}
                  style={captionStyle}
                  showSafeAreaGuides={showSafeAreaGuides}
                />
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void togglePlayback()}
                disabled={isBusy}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-sm text-zinc-200"
              >
                {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                {isPlaying ? "Pause" : "Play"}
              </button>
              <span className="text-sm text-zinc-500">
                {formatCaptionTimestamp(playbackTime)} / {formatCaptionTimestamp(clip.duration)}
              </span>
            </div>
          </div>

          <div className="flex min-h-[24rem] flex-col gap-4">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setEditorTab("segments")}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-medium",
                  editorTab === "segments"
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300",
                )}
              >
                Segments
              </button>
              <button
                type="button"
                onClick={() => setEditorTab("style")}
                disabled={segments.length === 0}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50",
                  editorTab === "style"
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300",
                )}
              >
                Style
              </button>
            </div>

            {editorTab === "style" ? (
              <div className="flex flex-col gap-4">
                <CaptionPresetPanel
                  currentStyle={captionStyle}
                  disabled={isBusy}
                  onApplyStyle={(style) => {
                    setCaptionStyle(style);
                    setStyleDirty(!stylesEqual(style, captions?.style ?? createDefaultCaptionStyle()));
                    setShowSafeAreaGuides(style.safe_area_mode !== "none");
                  }}
                  onError={setLocalError}
                />
                <CaptionStylePanel
                style={captionStyle}
                dirty={styleDirty}
                saving={styleSaving}
                resetting={styleResetting}
                disabled={isBusy || segments.length === 0}
                showSafeAreaGuides={showSafeAreaGuides}
                onStyleChange={handleStyleChange}
                onShowSafeAreaGuidesChange={setShowSafeAreaGuides}
                onSave={() => void handleSaveStyle()}
                onReset={() => void handleResetStyle()}
              />
              </div>
            ) : (
              <div className="flex min-h-[24rem] flex-col rounded-lg border border-zinc-800 bg-zinc-950/60">
                <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-4 py-3">
                  <button
                    type="button"
                    onClick={() => void onGenerate()}
                    disabled={isBusy}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 text-xs font-medium text-sky-100"
                  >
                    {generating ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    Generate captions
                  </button>
                  {captions ? (
                    <button
                      type="button"
                      onClick={() => void handleReset()}
                      disabled={isBusy}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3 text-xs font-medium text-red-100"
                    >
                      {resetting ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                      {confirmReset ? "Confirm reset" : "Reset captions"}
                    </button>
                  ) : null}
                </div>

                {loading ? (
                  <div className="flex flex-1 items-center justify-center text-sm text-zinc-500">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Loading captions...
                  </div>
                ) : segments.length === 0 ? (
                  <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-zinc-500">
                    <RefreshCw className="h-5 w-5 text-zinc-600" />
                    <p>No captions yet. Generate captions from the project transcript.</p>
                    <button
                      type="button"
                      onClick={() => void onGenerate()}
                      disabled={isBusy}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 text-xs font-medium text-sky-100"
                    >
                      Generate captions
                    </button>
                  </div>
                ) : (
                  <div className="flex-1 space-y-3 overflow-y-auto p-4">
                    {segments.map((segment) => {
                      const isActive = activeCaption?.id === segment.id;
                      const isSelected = selectedId === segment.id;

                      return (
                        <button
                          key={segment.id}
                          type="button"
                          onClick={() => {
                            setSelectedId(segment.id);
                            seekTo(segment.start);
                          }}
                          className={cn(
                            "w-full rounded-lg border px-3 py-3 text-left transition-colors",
                            isActive
                              ? "border-sky-500/40 bg-sky-500/10"
                              : isSelected
                                ? "border-zinc-700 bg-zinc-900"
                                : "border-zinc-800 bg-zinc-950 hover:bg-zinc-900/80",
                          )}
                        >
                          <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
                            <span>Caption {segment.sequence + 1}</span>
                            <span>
                              {formatCaptionTimestamp(segment.start)} –{" "}
                              {formatCaptionTimestamp(segment.end)}
                            </span>
                          </div>
                          <label className="block space-y-1">
                            <span className="text-xs text-zinc-500">Caption text</span>
                            <textarea
                              value={segment.text}
                              onClick={(event) => event.stopPropagation()}
                              onChange={(event) =>
                                updateSegment(segment.id, { text: event.target.value })
                              }
                              rows={2}
                              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
                            />
                          </label>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <label className="space-y-1">
                              <span className="text-xs text-zinc-500">Start time</span>
                              <input
                                aria-label={`Caption ${segment.sequence + 1} start time`}
                                value={formatCaptionTimestamp(segment.start)}
                                onClick={(event) => event.stopPropagation()}
                                onChange={(event) => {
                                  const parsed = parseCaptionTimestamp(event.target.value);
                                  if (parsed !== null) {
                                    updateSegment(segment.id, { start: parsed });
                                  }
                                }}
                                className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-xs text-zinc-100"
                              />
                            </label>
                            <label className="space-y-1">
                              <span className="text-xs text-zinc-500">End time</span>
                              <input
                                aria-label={`Caption ${segment.sequence + 1} end time`}
                                value={formatCaptionTimestamp(segment.end)}
                                onClick={(event) => event.stopPropagation()}
                                onChange={(event) => {
                                  const parsed = parseCaptionTimestamp(event.target.value);
                                  if (parsed !== null) {
                                    updateSegment(segment.id, { end: parsed });
                                  }
                                }}
                                className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-xs text-zinc-100"
                              />
                            </label>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-zinc-800 px-5 py-4">
          {error ? (
            <div className="mb-3 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          ) : null}
          {localError ? (
            <div className="mb-3 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-sm text-red-300">
              {localError}
            </div>
          ) : null}
          {validationError && segmentsDirty ? (
            <div className="mb-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
              {validationError}
            </div>
          ) : null}

          {renderSuccess ? (
            <div className="mb-3 rounded-lg border border-violet-500/20 bg-violet-500/5 px-3 py-2 text-sm text-violet-100">
              {renderSuccess}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => void handleRender()}
              disabled={isBusy || !canRender}
              aria-label="Export with captions"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-500/10 px-4 text-sm font-medium text-violet-100 disabled:opacity-50"
            >
              {rendering ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Video className="h-4 w-4" />
              )}
              Export with captions
            </button>
            <button
              type="button"
              onClick={onClose}
              disabled={isBusy}
              className="inline-flex h-9 items-center rounded-lg border border-zinc-800 px-4 text-sm text-zinc-300"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={
                isBusy || !captions || segments.length === 0 || !segmentsDirty || Boolean(validationError)
              }
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-medium text-emerald-100 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save captions
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export { buildCaptionUpdatePayload };
