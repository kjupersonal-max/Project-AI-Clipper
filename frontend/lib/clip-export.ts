import type { ClipCandidate, ExportClipRequest, ExportClipResponse, SegmentAnalysis } from "@/lib/api/projects";

export type CandidateExportStatus = "idle" | "exporting" | "completed" | "failed";

export type CandidateExportState = {
  status: CandidateExportStatus;
  error?: string;
};

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

function deriveClipNameFromText(text: string | undefined, start: number): string {
  const trimmed = text?.trim();
  if (trimmed) {
    const truncated = trimmed.slice(0, 60);
    return truncated.length < trimmed.length ? `${truncated}...` : truncated;
  }

  return `clip-${formatTimestamp(start)}`;
}

export function buildExportKeyFromSegment(segment: SegmentAnalysis): string {
  return `segment-${segment.segment_id}`;
}

export function buildExportKeyFromCandidate(candidate: ClipCandidate): string {
  return candidate.clip_id;
}

export function deriveClipNameFromSegment(segment: SegmentAnalysis): string {
  return deriveClipNameFromText(segment.text, segment.start);
}

export function deriveClipName(candidate: ClipCandidate): string {
  const title = candidate.title_suggestion?.trim();
  if (title) {
    return title;
  }

  return deriveClipNameFromText(candidate.transcript_text, candidate.start);
}

export function buildExportClipRequestFromSegment(
  segment: SegmentAnalysis,
): ExportClipRequest {
  return {
    start_time: segment.start,
    end_time: segment.end,
    clip_name: deriveClipNameFromSegment(segment),
    candidate_id: null,
  };
}

export function buildExportClipRequest(candidate: ClipCandidate): ExportClipRequest {
  return {
    start_time: candidate.start,
    end_time: candidate.end,
    clip_name: deriveClipName(candidate),
    candidate_id: candidate.clip_id,
  };
}

export function isCandidateExported(
  exportKey: string,
  exportedCandidateIds: ReadonlySet<string>,
  exportStates: Record<string, CandidateExportState>,
): boolean {
  if (exportedCandidateIds.has(exportKey)) {
    return true;
  }

  return exportStates[exportKey]?.status === "completed";
}

export function isCandidateExporting(
  exportKey: string,
  exportStates: Record<string, CandidateExportState>,
): boolean {
  return exportStates[exportKey]?.status === "exporting";
}

export function mergeExportedClips(
  saved: ExportClipResponse[],
  current: ExportClipResponse[],
): ExportClipResponse[] {
  const byId = new Map<string, ExportClipResponse>();

  for (const clip of saved) {
    byId.set(clip.clip_id, clip);
  }
  for (const clip of current) {
    byId.set(clip.clip_id, clip);
  }

  return [...byId.values()].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
  );
}

export function buildExportedStateFromClips(exports: ExportClipResponse[]): {
  exportedCandidateIds: Set<string>;
  exportStates: Record<string, CandidateExportState>;
} {
  const exportedCandidateIds = new Set<string>();
  const exportStates: Record<string, CandidateExportState> = {};

  for (const clip of exports) {
    if (!clip.candidate_id) {
      continue;
    }

    exportedCandidateIds.add(clip.candidate_id);
    exportStates[clip.candidate_id] = { status: "completed" };
  }

  return { exportedCandidateIds, exportStates };
}

export function applyLoadedExports(
  savedExports: ExportClipResponse[],
  currentClips: ExportClipResponse[],
  currentExportedCandidateIds: ReadonlySet<string>,
  currentExportStates: Record<string, CandidateExportState>,
): {
  exportedClips: ExportClipResponse[];
  exportedCandidateIds: Set<string>;
  exportStates: Record<string, CandidateExportState>;
} {
  const restored = buildExportedStateFromClips(savedExports);

  return {
    exportedClips: mergeExportedClips(savedExports, currentClips),
    exportedCandidateIds: new Set([
      ...restored.exportedCandidateIds,
      ...currentExportedCandidateIds,
    ]),
    exportStates: {
      ...restored.exportStates,
      ...currentExportStates,
    },
  };
}
