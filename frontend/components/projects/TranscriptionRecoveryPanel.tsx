"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type {
  ClipCaptionsResponse,
  TranscriptionQualityMode,
} from "@/lib/api/projects";
import {
  applyRetranscribeRange,
  deleteCaptionWordApi,
  insertCaptionSegmentApi,
  insertCaptionWordApi,
  mergeCaptionSegmentsApi,
  nudgeCaptionTimingApi,
  previewRetranscribeRange,
  splitCaptionSegmentApi,
  updateClipVocabularyHints,
} from "@/lib/api/projects";
import {
  buildCaptionUpdatePayload,
  cloneCaptionSegments,
  formatCaptionTimestamp,
  parseCaptionTimestamp,
  sortCaptionSegments,
  type CaptionSegment,
} from "@/lib/clip-captions";
import {
  qualityRatingClassName,
  qualityRatingLabel,
  sanitizeVocabularyHints,
  TRANSCRIPTION_QUALITY_MODES,
  validateRetranscribeRange,
} from "@/lib/transcription";
import { cn, uniqueStringListItems } from "@/lib/utils";
import { AlertTriangle, Loader2, Plus, RefreshCw, Scissors, Wand2 } from "lucide-react";

type TranscriptionRecoveryPanelProps = {
  projectId: string;
  clipId: string;
  clipDuration: number;
  captions: ClipCaptionsResponse;
  selectedSegmentId: string | null;
  playbackTime: number;
  disabled?: boolean;
  onCaptionsUpdated: (captions: ClipCaptionsResponse) => void;
  onSegmentsUpdated: (segments: CaptionSegment[]) => void;
  onError: (message: string | null) => void;
};

export function TranscriptionRecoveryPanel({
  projectId,
  clipId,
  clipDuration,
  captions,
  selectedSegmentId,
  playbackTime,
  disabled = false,
  onCaptionsUpdated,
  onSegmentsUpdated,
  onError,
}: TranscriptionRecoveryPanelProps) {
  const [qualityMode, setQualityMode] = useState<TranscriptionQualityMode>(
    captions.transcription_quality_mode ?? "balanced",
  );
  const [vocabularyHints, setVocabularyHints] = useState(captions.vocabulary_hints ?? "");
  const [rangeStart, setRangeStart] = useState("0:0.000");
  const [rangeEnd, setRangeEnd] = useState(formatCaptionTimestamp(Math.min(clipDuration, 3)));
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSegments, setPreviewSegments] = useState<CaptionSegment[]>([]);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>([]);
  const [manualEditWarnings, setManualEditWarnings] = useState<string[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  const selectedMode = useMemo(
    () => TRANSCRIPTION_QUALITY_MODES.find((mode) => mode.value === qualityMode),
    [qualityMode],
  );

  const runLocked = useCallback(
    async (action: string, task: () => Promise<void>) => {
      if (disabled || inFlightRef.current) {
        return;
      }
      inFlightRef.current = true;
      setBusyAction(action);
      onError(null);
      try {
        await task();
      } finally {
        inFlightRef.current = false;
        setBusyAction(null);
      }
    },
    [disabled, onError],
  );

  const handleSaveVocabularyHints = useCallback(async () => {
    await runLocked("vocabulary", async () => {
      const updated = await updateClipVocabularyHints(
        projectId,
        clipId,
        sanitizeVocabularyHints(vocabularyHints) || null,
      );
      onCaptionsUpdated(updated);
    });
  }, [clipId, onCaptionsUpdated, projectId, runLocked, vocabularyHints]);

  const handlePreviewRange = useCallback(async () => {
    const start = parseCaptionTimestamp(rangeStart);
    const end = parseCaptionTimestamp(rangeEnd);
    if (start === null || end === null) {
      onError("Invalid range timestamps.");
      return;
    }
    const validationError = validateRetranscribeRange(start, end, clipDuration);
    if (validationError) {
      onError(validationError);
      return;
    }

    await runLocked("preview", async () => {
      const preview = await previewRetranscribeRange(projectId, clipId, {
        start_time: start,
        end_time: end,
        quality_mode: qualityMode,
        vocabulary_hints: sanitizeVocabularyHints(vocabularyHints) || null,
      });
      setPreviewSegments(cloneCaptionSegments(preview.preview_segments));
      setPreviewWarnings(preview.warnings);
      setManualEditWarnings(preview.manual_edit_warnings);
      setPreviewOpen(true);
    });
  }, [
    clipDuration,
    clipId,
    onError,
    projectId,
    qualityMode,
    rangeEnd,
    rangeStart,
    runLocked,
    vocabularyHints,
  ]);

  const handleApplyPreview = useCallback(async () => {
    const start = parseCaptionTimestamp(rangeStart);
    const end = parseCaptionTimestamp(rangeEnd);
    if (start === null || end === null) {
      onError("Invalid range timestamps.");
      return;
    }

    await runLocked("apply", async () => {
      const updated = await applyRetranscribeRange(projectId, clipId, {
        start_time: start,
        end_time: end,
        preview_segments: buildCaptionUpdatePayload(previewSegments),
        mode: "replace",
      });
      onCaptionsUpdated(updated);
      onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
      setPreviewOpen(false);
    });
  }, [
    clipId,
    onCaptionsUpdated,
    onError,
    onSegmentsUpdated,
    previewSegments,
    projectId,
    rangeEnd,
    rangeStart,
    runLocked,
  ]);

  const handleInsertWord = useCallback(async () => {
    if (!selectedSegmentId) {
      onError("Select a caption segment first.");
      return;
    }
    const word = window.prompt("Word to insert");
    if (!word?.trim()) {
      return;
    }
    await runLocked("insert-word", async () => {
      const updated = await insertCaptionWordApi(projectId, clipId, {
        segment_id: selectedSegmentId,
        word: word.trim(),
        start: playbackTime,
        end: Math.min(clipDuration, playbackTime + 0.4),
      });
      onCaptionsUpdated(updated);
      onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
    });
  }, [
    clipDuration,
    clipId,
    onCaptionsUpdated,
    onError,
    onSegmentsUpdated,
    playbackTime,
    projectId,
    runLocked,
    selectedSegmentId,
  ]);

  const handleInsertSegment = useCallback(async () => {
    const text = window.prompt("Caption text");
    if (!text?.trim()) {
      return;
    }
    await runLocked("insert-segment", async () => {
      const updated = await insertCaptionSegmentApi(projectId, clipId, {
        text: text.trim(),
        start: playbackTime,
        end: Math.min(clipDuration, playbackTime + 1.5),
      });
      onCaptionsUpdated(updated);
      onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
    });
  }, [
    clipDuration,
    clipId,
    onCaptionsUpdated,
    onSegmentsUpdated,
    playbackTime,
    projectId,
    runLocked,
  ]);

  const handleSplit = useCallback(async () => {
    if (!selectedSegmentId) {
      onError("Select a caption segment first.");
      return;
    }
    await runLocked("split", async () => {
      const updated = await splitCaptionSegmentApi(projectId, clipId, {
        segment_id: selectedSegmentId,
        split_time: playbackTime,
      });
      onCaptionsUpdated(updated);
      onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
    });
  }, [
    clipId,
    onCaptionsUpdated,
    onError,
    onSegmentsUpdated,
    playbackTime,
    projectId,
    runLocked,
    selectedSegmentId,
  ]);

  const handleMerge = useCallback(async () => {
    const segments = sortCaptionSegments(captions.segments);
    const selectedIndex = segments.findIndex((segment) => segment.id === selectedSegmentId);
    if (selectedIndex < 0 || selectedIndex >= segments.length - 1) {
      onError("Select a segment that has a following segment to merge.");
      return;
    }
    await runLocked("merge", async () => {
      const updated = await mergeCaptionSegmentsApi(projectId, clipId, {
        first_segment_id: segments[selectedIndex].id,
        second_segment_id: segments[selectedIndex + 1].id,
      });
      onCaptionsUpdated(updated);
      onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
    });
  }, [
    captions.segments,
    clipId,
    onCaptionsUpdated,
    onError,
    onSegmentsUpdated,
    projectId,
    runLocked,
    selectedSegmentId,
  ]);

  const handleNudge = useCallback(
    async (delta: number) => {
      if (!selectedSegmentId) {
        onError("Select a caption segment first.");
        return;
      }
      await runLocked(`nudge-${delta}`, async () => {
        const updated = await nudgeCaptionTimingApi(projectId, clipId, {
          segment_id: selectedSegmentId,
          delta_seconds: delta,
        });
        onCaptionsUpdated(updated);
        onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
      });
    },
    [clipId, onCaptionsUpdated, onError, onSegmentsUpdated, projectId, runLocked, selectedSegmentId],
  );

  const handleDeleteWord = useCallback(async () => {
    if (!selectedSegmentId) {
      onError("Select a caption segment first.");
      return;
    }
    const segment = captions.segments.find((item) => item.id === selectedSegmentId);
    if (!segment || segment.words.length === 0) {
      onError("Selected segment has no words to delete.");
      return;
    }
    await runLocked("delete-word", async () => {
      const updated = await deleteCaptionWordApi(projectId, clipId, {
        segment_id: selectedSegmentId,
        word_index: segment.words.length - 1,
      });
      onCaptionsUpdated(updated);
      onSegmentsUpdated(cloneCaptionSegments(sortCaptionSegments(updated.segments)));
    });
  }, [
    captions.segments,
    clipId,
    onCaptionsUpdated,
    onError,
    onSegmentsUpdated,
    projectId,
    runLocked,
    selectedSegmentId,
  ]);

  const isBusy = Boolean(busyAction);

  return (
    <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-zinc-100">Transcription quality</h3>
          <p className="text-xs text-zinc-500">
            Improve recognition and recover missed speech without changing caption styling.
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-xs",
            qualityRatingClassName(captions.transcription_quality_rating),
          )}
        >
          {qualityRatingLabel(captions.transcription_quality_rating)}
        </span>
      </div>

      {(captions.transcription_warnings ?? []).length > 0 ? (
        <div className="space-y-1 rounded-md border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-100">
          {uniqueStringListItems(captions.transcription_warnings, "caption-warning").map(
            (warning) => (
              <p key={warning.key}>{warning.text}</p>
            ),
          )}
        </div>
      ) : null}

      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">Quality mode</span>
        <select
          value={qualityMode}
          disabled={disabled || isBusy}
          onChange={(event) => setQualityMode(event.target.value as TranscriptionQualityMode)}
          className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
        >
          {TRANSCRIPTION_QUALITY_MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>
              {mode.label}
            </option>
          ))}
        </select>
        {selectedMode?.warning ? (
          <p className="flex items-start gap-1 text-xs text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {selectedMode.warning}
          </p>
        ) : null}
      </label>

      <label className="block space-y-1">
        <span className="text-xs text-zinc-500">Vocabulary hints</span>
        <textarea
          value={vocabularyHints}
          disabled={disabled || isBusy}
          onChange={(event) => setVocabularyHints(event.target.value)}
          rows={2}
          placeholder="Names, brands, slang, technical terms..."
          className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
        />
        <button
          type="button"
          disabled={disabled || isBusy}
          onClick={() => void handleSaveVocabularyHints()}
          className="inline-flex h-7 items-center rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
        >
          {busyAction === "vocabulary" ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : null}
          Save hints
        </button>
      </label>

      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <p className="text-xs font-medium text-zinc-300">Retranscribe selected range</p>
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-xs text-zinc-500">Start</span>
            <input
              value={rangeStart}
              disabled={disabled || isBusy}
              onChange={(event) => setRangeStart(event.target.value)}
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-xs text-zinc-100"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-500">End</span>
            <input
              value={rangeEnd}
              disabled={disabled || isBusy}
              onChange={(event) => setRangeEnd(event.target.value)}
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-xs text-zinc-100"
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handlePreviewRange()}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 text-xs text-sky-100"
          >
            {busyAction === "preview" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Wand2 className="h-3.5 w-3.5" />
            )}
            Preview replacement
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => {
              setRangeStart(formatCaptionTimestamp(Math.max(0, playbackTime - 0.5)));
              setRangeEnd(formatCaptionTimestamp(Math.min(clipDuration, playbackTime + 0.5)));
            }}
            className="inline-flex h-8 items-center rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            Use playback range
          </button>
        </div>
      </div>

      {previewOpen ? (
        <div className="space-y-2 rounded-md border border-violet-500/20 bg-violet-500/5 p-3">
          <p className="text-xs font-medium text-violet-100">Preview replacement</p>
          {uniqueStringListItems(previewWarnings, "preview-warning").map((warning) => (
            <p key={warning.key} className="text-xs text-amber-100">
              {warning.text}
            </p>
          ))}
          {uniqueStringListItems(manualEditWarnings, "manual-edit-warning").map((warning) => (
            <p key={warning.key} className="text-xs text-amber-100">
              {warning.text}
            </p>
          ))}
          <div className="max-h-32 space-y-1 overflow-y-auto">
            {previewSegments.map((segment) => (
              <p key={segment.id} className="text-xs text-zinc-200">
                {formatCaptionTimestamp(segment.start)} – {formatCaptionTimestamp(segment.end)}:{" "}
                {segment.text}
              </p>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={disabled || isBusy}
              onClick={() => void handleApplyPreview()}
              className="inline-flex h-8 items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 text-xs text-emerald-100"
            >
              {busyAction === "apply" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Apply to range
            </button>
            <button
              type="button"
              disabled={disabled || isBusy}
              onClick={() => setPreviewOpen(false)}
              className="inline-flex h-8 items-center rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <p className="text-xs font-medium text-zinc-300">Manual recovery</p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleInsertWord()}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            <Plus className="h-3.5 w-3.5" />
            Insert word
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleInsertSegment()}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            <Plus className="h-3.5 w-3.5" />
            Insert segment
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleSplit()}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            <Scissors className="h-3.5 w-3.5" />
            Split
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleMerge()}
            className="inline-flex h-8 items-center rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            Merge next
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleNudge(-0.1)}
            className="inline-flex h-8 items-center rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            Nudge -0.1s
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleNudge(0.1)}
            className="inline-flex h-8 items-center rounded-md border border-zinc-700 px-2 text-xs text-zinc-300"
          >
            Nudge +0.1s
          </button>
          <button
            type="button"
            disabled={disabled || isBusy}
            onClick={() => void handleDeleteWord()}
            className="inline-flex h-8 items-center rounded-md border border-red-500/30 px-2 text-xs text-red-200"
          >
            Delete last word
          </button>
        </div>
        <p className="text-xs text-zinc-500">
          Manually edited captions are marked in the segment list. Overlapping speech may still
          require manual correction.
        </p>
      </div>
    </div>
  );
}
