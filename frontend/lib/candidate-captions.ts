import type { ClipCandidate, ExportClipResponse } from "@/lib/api/projects";

export type CandidateCaptionStatus =
  | "not_generated"
  | "generating"
  | "completed"
  | "failed";

export type CandidateCaptionState = {
  status: CandidateCaptionStatus;
  error?: string | null;
};

export function createInitialCandidateCaptionState(): CandidateCaptionState {
  return { status: "not_generated" };
}

export function buildCaptionTargetFromCandidate(
  candidate: ClipCandidate,
  projectId: string,
): ExportClipResponse {
  return {
    clip_id: candidate.clip_id,
    project_id: projectId,
    filename: `${candidate.title_suggestion.replace(/\s+/g, "-").toLowerCase()}.mp4`,
    relative_path: "",
    media_url: "",
    start_time: candidate.start,
    end_time: candidate.end,
    duration: candidate.duration,
    file_size_bytes: 0,
    candidate_id: candidate.clip_id,
    clip_name: candidate.title_suggestion,
    created_at: new Date().toISOString(),
    export_status: "completed",
    is_favorite: false,
  };
}

export function candidateCaptionStatusLabel(status: CandidateCaptionStatus): string {
  switch (status) {
    case "not_generated":
      return "Captions not generated";
    case "generating":
      return "Generating captions";
    case "completed":
      return "Captions ready";
    case "failed":
      return "Caption generation failed";
    default:
      return status;
  }
}
