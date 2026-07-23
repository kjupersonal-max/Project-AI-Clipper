"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ExportClipResponse } from "@/lib/api/projects";
import {
  clampPlaybackTime,
  clampTrimTime,
  computeTrimDuration,
  deriveTrimmedClipName,
  formatTrimTimestamp,
  getFrameStep,
  getTrimBounds,
  normalizeTrimRange,
  parseTrimTimestamp,
  stepTrimTime,
  validateTrimRange,
} from "@/lib/clip-trim";
import { getClipDisplayName } from "@/lib/exported-clips-library";
import { cn, formatDuration } from "@/lib/utils";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  Pause,
  Play,
  Save,
  X,
} from "lucide-react";

type ClipEditorProps = {
  clip: ExportClipResponse;
  sourceVideoUrl: string;
  frameRate?: number | null;
  saving?: boolean;
  error?: string | null;
  onSave: (payload: { startTime: number; endTime: number; clipName: string }) => Promise<void>;
  onClose: () => void;
};

type ActiveHandle = "start" | "end";

const PLAYBACK_SPEEDS = [0.5, 1, 1.5, 2] as const;

type TrimTimelineProps = {
  bounds: { minStart: number; maxEnd: number };
  startTime: number;
  endTime: number;
  currentTime: number;
  disabled?: boolean;
  onStartChange: (value: number) => void;
  onEndChange: (value: number) => void;
  onSeek: (value: number) => void;
};

function TrimTimeline({
  bounds,
  startTime,
  endTime,
  currentTime,
  disabled = false,
  onStartChange,
  onEndChange,
  onSeek,
}: TrimTimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<ActiveHandle | null>(null);

  const range = bounds.maxEnd - bounds.minStart;

  function toPercent(value: number): number {
    if (range <= 0) {
      return 0;
    }
    return ((value - bounds.minStart) / range) * 100;
  }

  function valueFromClientX(clientX: number): number {
    const track = trackRef.current;
    if (!track || range <= 0) {
      return bounds.minStart;
    }

    const rect = track.getBoundingClientRect();
    const ratio = clampTrimTime((clientX - rect.left) / rect.width, 0, 1);
    return bounds.minStart + ratio * range;
  }

  useEffect(() => {
    function valueFromClientX(clientX: number): number {
      const track = trackRef.current;
      if (!track || range <= 0) {
        return bounds.minStart;
      }

      const rect = track.getBoundingClientRect();
      const ratio = clampTrimTime((clientX - rect.left) / rect.width, 0, 1);
      return bounds.minStart + ratio * range;
    }

    function handlePointerMove(event: PointerEvent) {
      if (!dragRef.current) {
        return;
      }

      const nextValue = valueFromClientX(event.clientX);
      if (dragRef.current === "start") {
        onStartChange(nextValue);
      } else {
        onEndChange(nextValue);
      }
    }

    function handlePointerUp() {
      dragRef.current = null;
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [bounds.maxEnd, bounds.minStart, onEndChange, onStartChange, range]);

  function startDrag(handle: ActiveHandle) {
    if (disabled) {
      return;
    }
    dragRef.current = handle;
  }

  function handleTrackClick(event: React.MouseEvent<HTMLDivElement>) {
    if (disabled || dragRef.current) {
      return;
    }
    onSeek(valueFromClientX(event.clientX));
  }

  const startPercent = toPercent(startTime);
  const endPercent = toPercent(endTime);
  const playheadPercent = toPercent(currentTime);

  return (
    <div className="space-y-2">
      <div
        ref={trackRef}
        onClick={handleTrackClick}
        className={cn(
          "relative h-12 rounded-lg border border-zinc-800 bg-zinc-950/70",
          disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        )}
      >
        <div
          className="absolute inset-y-3 rounded bg-emerald-500/20"
          style={{
            left: `${startPercent}%`,
            width: `${Math.max(endPercent - startPercent, 0)}%`,
          }}
        />
        <div
          className="absolute top-2 bottom-2 w-0.5 bg-sky-400"
          style={{ left: `${playheadPercent}%` }}
        />
        <button
          type="button"
          aria-label="Trim start handle"
          disabled={disabled}
          onPointerDown={(event) => {
            event.stopPropagation();
            startDrag("start");
          }}
          className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-emerald-300 bg-emerald-500 shadow"
          style={{ left: `${startPercent}%` }}
        />
        <button
          type="button"
          aria-label="Trim end handle"
          disabled={disabled}
          onPointerDown={(event) => {
            event.stopPropagation();
            startDrag("end");
          }}
          className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-emerald-300 bg-emerald-500 shadow"
          style={{ left: `${endPercent}%` }}
        />
      </div>
      <div className="flex justify-between text-xs font-mono text-zinc-500">
        <span>{formatTrimTimestamp(bounds.minStart)}</span>
        <span>{formatTrimTimestamp(bounds.maxEnd)}</span>
      </div>
    </div>
  );
}

export function ClipEditor({
  clip,
  sourceVideoUrl,
  frameRate = null,
  saving = false,
  error = null,
  onSave,
  onClose,
}: ClipEditorProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const bounds = useMemo(
    () => getTrimBounds(clip.start_time, clip.end_time),
    [clip.end_time, clip.start_time],
  );

  const [startTime, setStartTime] = useState(clip.start_time);
  const [endTime, setEndTime] = useState(clip.end_time);
  const [clipName, setClipName] = useState(
    deriveTrimmedClipName(clip.clip_name, clip.filename),
  );
  const [playbackRate, setPlaybackRate] = useState<number>(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(clip.start_time);
  const [activeHandle, setActiveHandle] = useState<ActiveHandle>("start");
  const [localError, setLocalError] = useState<string | null>(null);

  const duration = computeTrimDuration(startTime, endTime);
  const validationError = validateTrimRange(startTime, endTime, bounds);
  const frameStep = getFrameStep(frameRate);

  const applyTrimRange = useCallback(
    (nextStart: number, nextEnd: number) => {
      const normalized = normalizeTrimRange(nextStart, nextEnd, bounds);
      setStartTime(normalized.startTime);
      setEndTime(normalized.endTime);
      setLocalError(null);

      const video = videoRef.current;
      if (!video) {
        setCurrentTime(normalized.startTime);
        return;
      }

      const clamped = clampPlaybackTime(video.currentTime, normalized.startTime, normalized.endTime);
      video.currentTime = clamped;
      setCurrentTime(clamped);
    },
    [bounds],
  );

  const seekTo = useCallback(
    (time: number) => {
      const clamped = clampPlaybackTime(time, startTime, endTime);
      const video = videoRef.current;
      if (video) {
        video.currentTime = clamped;
      }
      setCurrentTime(clamped);
    },
    [endTime, startTime],
  );

  const togglePlayback = useCallback(async () => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    if (video.paused) {
      if (video.currentTime >= endTime || video.currentTime < startTime) {
        video.currentTime = startTime;
      }
      await video.play();
    } else {
      video.pause();
    }
  }, [endTime, startTime]);

  const stepActiveHandle = useCallback(
    (frames: number) => {
      if (activeHandle === "start") {
        applyTrimRange(stepTrimTime(startTime, frames, frameRate), endTime);
        return;
      }
      applyTrimRange(startTime, stepTrimTime(endTime, frames, frameRate));
    },
    [activeHandle, applyTrimRange, endTime, frameRate, startTime],
  );

  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    video.playbackRate = playbackRate;
  }, [playbackRate]);

  useEffect(() => {
    const videoElement = videoRef.current;
    if (!videoElement) {
      return;
    }
    const element: HTMLVideoElement = videoElement;

    function handleLoadedMetadata() {
      element.currentTime = startTime;
      setCurrentTime(startTime);
    }

    function handleTimeUpdate() {
      if (element.currentTime > endTime) {
        element.pause();
        element.currentTime = endTime;
        setIsPlaying(false);
      }
      if (element.currentTime < startTime) {
        element.currentTime = startTime;
      }
      setCurrentTime(element.currentTime);
    }

    function handlePlay() {
      setIsPlaying(true);
    }

    function handlePause() {
      setIsPlaying(false);
    }

    element.addEventListener("loadedmetadata", handleLoadedMetadata);
    element.addEventListener("timeupdate", handleTimeUpdate);
    element.addEventListener("play", handlePlay);
    element.addEventListener("pause", handlePause);

    return () => {
      element.removeEventListener("loadedmetadata", handleLoadedMetadata);
      element.removeEventListener("timeupdate", handleTimeUpdate);
      element.removeEventListener("play", handlePlay);
      element.removeEventListener("pause", handlePause);
    };
  }, [endTime, startTime]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key === " " && event.target === document.body) {
        event.preventDefault();
        void togglePlayback();
        return;
      }

      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepActiveHandle(-1);
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        stepActiveHandle(1);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, stepActiveHandle, togglePlayback]);

  function handleNumericChange(field: ActiveHandle, value: string) {
    const parsed = parseTrimTimestamp(value);
    if (parsed == null) {
      setLocalError("Enter a valid timestamp such as 0:12.500.");
      return;
    }

    if (field === "start") {
      applyTrimRange(parsed, endTime);
      return;
    }
    applyTrimRange(startTime, parsed);
  }

  async function handleSave() {
    const errorMessage = validateTrimRange(startTime, endTime, bounds);
    if (errorMessage) {
      setLocalError(errorMessage);
      return;
    }

    setLocalError(null);
    try {
      await onSave({
        startTime,
        endTime,
        clipName: clipName.trim() || deriveTrimmedClipName(clip.clip_name, clip.filename),
      });
    } catch {
      // Parent surfaces API errors through the error prop.
    }
  }

  const displayError = localError || error;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Edit clip ${getClipDisplayName(clip)}`}
        className="flex max-h-[95vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-zinc-800 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Edit clip</h2>
            <p className="mt-1 text-sm text-zinc-400">
              Fine-tune trim points for {getClipDisplayName(clip)}. Saving creates a new exported clip and leaves the original unchanged.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            aria-label="Close editor"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 text-zinc-300 transition-colors hover:bg-zinc-900"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5 overflow-y-auto px-5 py-5">
          <div className="overflow-hidden rounded-lg border border-zinc-800 bg-black">
            <video
              ref={videoRef}
              src={sourceVideoUrl}
              controls={false}
              preload="metadata"
              className="aspect-video w-full bg-black"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void togglePlayback()}
              disabled={saving}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-sm text-zinc-200 hover:bg-zinc-800"
            >
              {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {isPlaying ? "Pause" : "Play trim"}
            </button>

            <label className="flex items-center gap-2 text-sm text-zinc-400">
              Speed
              <select
                value={playbackRate}
                onChange={(event) => setPlaybackRate(Number(event.target.value))}
                disabled={saving}
                aria-label="Playback speed"
                className="rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100"
              >
                {PLAYBACK_SPEEDS.map((speed) => (
                  <option key={speed} value={speed}>
                    {speed}x
                  </option>
                ))}
              </select>
            </label>

            <span className="text-sm text-zinc-400">
              Duration: <span className="font-medium text-zinc-200">{formatDuration(duration)}</span>
            </span>
            <span className="text-sm font-mono text-zinc-500">
              Frame step: {frameStep.toFixed(3)}s
            </span>
          </div>

          <TrimTimeline
            bounds={bounds}
            startTime={startTime}
            endTime={endTime}
            currentTime={currentTime}
            disabled={saving}
            onStartChange={(value) => applyTrimRange(value, endTime)}
            onEndChange={(value) => applyTrimRange(startTime, value)}
            onSeek={seekTo}
          />

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-xs font-medium text-zinc-400" htmlFor="trim-start">
                Start time
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="trim-start"
                  type="text"
                  value={formatTrimTimestamp(startTime)}
                  onChange={(event) => handleNumericChange("start", event.target.value)}
                  onFocus={() => setActiveHandle("start")}
                  disabled={saving}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-100"
                />
                <button
                  type="button"
                  aria-label="Step start backward one frame"
                  disabled={saving}
                  onClick={() => {
                    setActiveHandle("start");
                    stepActiveHandle(-1);
                  }}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Step start forward one frame"
                  disabled={saving}
                  onClick={() => {
                    setActiveHandle("start");
                    stepActiveHandle(1);
                  }}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-medium text-zinc-400" htmlFor="trim-end">
                End time
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="trim-end"
                  type="text"
                  value={formatTrimTimestamp(endTime)}
                  onChange={(event) => handleNumericChange("end", event.target.value)}
                  onFocus={() => setActiveHandle("end")}
                  disabled={saving}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-100"
                />
                <button
                  type="button"
                  aria-label="Step end backward one frame"
                  disabled={saving}
                  onClick={() => {
                    setActiveHandle("end");
                    stepActiveHandle(-1);
                  }}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Step end forward one frame"
                  disabled={saving}
                  onClick={() => {
                    setActiveHandle("end");
                    stepActiveHandle(1);
                  }}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-300"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-zinc-400" htmlFor="trim-clip-name">
              New clip name
            </label>
            <input
              id="trim-clip-name"
              type="text"
              value={clipName}
              onChange={(event) => setClipName(event.target.value)}
              disabled={saving}
              className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
            />
          </div>

          {displayError ? (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-sm text-red-300">
              {displayError}
            </div>
          ) : null}

          {validationError && !displayError ? (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
              {validationError}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-zinc-800 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="inline-flex h-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 px-4 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || Boolean(validationError)}
            className={cn(
              "inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-medium text-emerald-100 hover:bg-emerald-500/20",
              (saving || validationError) && "cursor-not-allowed opacity-60",
            )}
          >
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving trimmed clip...
              </>
            ) : (
              <>
                <Save className="h-4 w-4" />
                Save as new clip
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
