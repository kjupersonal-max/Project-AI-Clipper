import { API_BASE_URL } from "@/lib/config";

export type ProcessingStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "skipped";

export type VideoMetadata = {
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  frame_rate: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  sample_rate: number | null;
  audio_channels: number | null;
  file_size: number | null;
  aspect_ratio: string | null;
  has_audio: boolean;
  has_video: boolean;
};

export type ActivityLogEntry = {
  timestamp: string;
  level: string;
  message: string;
};

export type Project = {
  project_id: string;
  original_filename: string;
  stored_video_path: string;
  upload_status: ProcessingStatus;
  inspection_status: ProcessingStatus;
  audio_extraction_status: ProcessingStatus;
  transcription_status: ProcessingStatus;
  video_metadata: VideoMetadata | null;
  extracted_audio_path: string | null;
  extracted_audio_duration_seconds: number | null;
  transcript_path: string | null;
  detected_language: string | null;
  transcription_started_at: string | null;
  transcription_completed_at: string | null;
  analysis_status: ProcessingStatus;
  analysis_path: string | null;
  analysis_started_at: string | null;
  analysis_completed_at: string | null;
  analysis_provider: string | null;
  clip_selection_status: ProcessingStatus;
  clip_candidates_path: string | null;
  clip_selection_started_at: string | null;
  clip_selection_completed_at: string | null;
  clip_candidate_count: number | null;
  size_bytes: number;
  activity_log: ActivityLogEntry[];
  created_at: string;
  updated_at: string;
  last_error: string | null;
};

export type InspectResponse = {
  project_id: string;
  inspection_status: ProcessingStatus;
  video_metadata: VideoMetadata;
  message: string;
};

export type ExtractAudioResponse = {
  project_id: string;
  audio_extraction_status: ProcessingStatus;
  extracted_audio_path: string;
  duration_seconds: number | null;
  status: string;
  message: string;
};

export type TranscriptWord = {
  word: string;
  start: number;
  end: number;
  probability: number | null;
};

export type TranscriptSegment = {
  id: number;
  start: number;
  end: number;
  text: string;
  words: TranscriptWord[];
};

export type TranscriptDocument = {
  project_id: string;
  language: string;
  duration: number;
  segment_count: number;
  word_count: number;
  segments: TranscriptSegment[];
  created_at: string;
};

export type TranscribeResponse = {
  project_id: string;
  status: string;
  language: string;
  duration: number;
  segment_count: number;
  word_count: number;
  transcript_path: string;
};

export type SegmentAnalysis = {
  segment_id: number;
  start: number;
  end: number;
  text: string;
  emotion: string;
  excitement_score: number;
  humor_score: number;
  suspense_score: number;
  educational_score: number;
  standalone_score: number;
  context_dependency_score: number;
  clip_candidate: boolean;
  reason: string;
};

export type AnalysisDocument = {
  project_id: string;
  provider: string;
  model: string | null;
  is_heuristic_fallback: boolean;
  segment_count: number;
  clip_candidate_count: number;
  segments: SegmentAnalysis[];
  created_at: string;
};

export type AnalyzeResponse = {
  project_id: string;
  status: string;
  provider: string;
  model: string | null;
  is_heuristic_fallback: boolean;
  segment_count: number;
  clip_candidate_count: number;
  analysis_path: string;
};

export type ClipCandidate = {
  clip_id: string;
  start: number;
  end: number;
  duration: number;
  segment_ids: number[];
  transcript_text: string;
  score: number;
  confidence: number;
  primary_emotion: string;
  hook_score: number;
  payoff_score: number;
  standalone_score: number;
  context_dependency_score: number;
  title_suggestion: string;
  reason: string;
  status: string;
};

export type ClipCandidatesDocument = {
  project_id: string;
  candidate_count: number;
  min_duration_seconds: number;
  max_duration_seconds: number;
  max_gap_seconds: number;
  max_candidates: number;
  source_duration_seconds: number;
  candidates: ClipCandidate[];
  created_at: string;
};

export type SelectClipsRequest = {
  min_duration_seconds?: number | null;
  max_duration_seconds?: number | null;
  max_gap_seconds?: number | null;
  max_candidates?: number | null;
  min_score?: number | null;
};

export type SelectClipsResponse = {
  project_id: string;
  status: string;
  candidate_count: number;
  clip_candidates_path: string;
};

export type ExportClipRequest = {
  start_time: number;
  end_time: number;
  clip_name?: string | null;
  candidate_id?: string | null;
};

export type ExportClipResponse = {
  clip_id: string;
  project_id: string;
  filename: string;
  relative_path: string;
  media_url: string;
  start_time: number;
  end_time: number;
  duration: number;
  file_size_bytes: number;
  candidate_id: string | null;
  clip_name: string | null;
  created_at: string;
  export_status: ProcessingStatus;
  is_favorite: boolean;
  export_kind?: "raw" | "captioned";
  source_clip_id?: string | null;
  caption_style_preset?: string | null;
};

export type ClipExportsListResponse = {
  project_id: string;
  exports: ExportClipResponse[];
};

export type RenameClipRequest = {
  clip_name: string;
};

export type FavoriteClipRequest = {
  is_favorite: boolean;
};

export type TrimClipRequest = {
  start_time: number;
  end_time: number;
  clip_name?: string | null;
};

export type DeleteClipResponse = {
  project_id: string;
  clip_id: string;
  message: string;
};

export type CaptionWord = {
  word: string;
  start: number;
  end: number;
};

export type {
  CaptionStyle,
  CaptionStylePresetId,
  CaptionAnimationType,
  CaptionWordsPerGroup,
  CaptionSafeAreaMode,
} from "@/lib/caption-style";

import type { CaptionStyle } from "@/lib/caption-style";

export type CaptionSegment = {
  id: string;
  text: string;
  start: number;
  end: number;
  words: CaptionWord[];
  sequence: number;
  created_at: string;
  updated_at: string;
};

export type ClipCaptionsResponse = {
  project_id: string;
  clip_id: string;
  source_start_time: number;
  source_end_time: number;
  duration: number;
  candidate_id: string | null;
  segments: CaptionSegment[];
  style: CaptionStyle;
  created_at: string;
  updated_at: string;
};

export type UpdateCaptionSegmentRequest = {
  id: string;
  text: string;
  start: number;
  end: number;
  words?: CaptionWord[];
  sequence: number;
};

export type UpdateCaptionsRequest = {
  segments: UpdateCaptionSegmentRequest[];
};

export type UpdateCaptionStyleRequest = {
  style: CaptionStyle;
};

export type DeleteCaptionsResponse = {
  project_id: string;
  clip_id: string;
  message: string;
};

export type ApiError = {
  message: string;
  status?: number;
};

async function parseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Fall through.
  }

  return response.statusText || "Request failed.";
}

export async function fetchProject(projectId: string): Promise<Project> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<Project>;
}

export async function inspectProject(projectId: string): Promise<InspectResponse> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/inspect`, {
    method: "POST",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<InspectResponse>;
}

export async function extractProjectAudio(
  projectId: string,
): Promise<ExtractAudioResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/extract-audio`,
    { method: "POST" },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ExtractAudioResponse>;
}

export async function transcribeProject(
  projectId: string,
): Promise<TranscribeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/transcribe`, {
    method: "POST",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<TranscribeResponse>;
}

export async function fetchProjectTranscript(
  projectId: string,
): Promise<TranscriptDocument> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/transcript`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<TranscriptDocument>;
}

export async function analyzeProject(projectId: string): Promise<AnalyzeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/analyze`, {
    method: "POST",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<AnalyzeResponse>;
}

export async function fetchProjectAnalysis(projectId: string): Promise<AnalysisDocument> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/analysis`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<AnalysisDocument>;
}

export async function selectProjectClips(
  projectId: string,
  request: SelectClipsRequest = {},
): Promise<SelectClipsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/select-clips`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<SelectClipsResponse>;
}

export async function fetchProjectClipCandidates(
  projectId: string,
): Promise<ClipCandidatesDocument> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/clip-candidates`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipCandidatesDocument>;
}

export function getProjectVideoUrl(projectId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/media/video`;
}

export function getProjectClipMediaUrl(projectId: string, clipId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/media/clips/${clipId}`;
}

export function resolveMediaUrl(mediaUrl: string): string {
  if (mediaUrl.startsWith("http://") || mediaUrl.startsWith("https://")) {
    return mediaUrl;
  }

  const path = mediaUrl.startsWith("/") ? mediaUrl : `/${mediaUrl}`;
  return `${API_BASE_URL.replace(/\/$/, "")}${path}`;
}

export async function exportProjectClip(
  projectId: string,
  request: ExportClipRequest,
): Promise<ExportClipResponse> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/clips/export`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ExportClipResponse>;
}

export async function fetchProjectClipExports(
  projectId: string,
): Promise<ClipExportsListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/clips/exports`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipExportsListResponse>;
}

export async function renameProjectClip(
  projectId: string,
  clipId: string,
  request: RenameClipRequest,
): Promise<ExportClipResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ExportClipResponse>;
}

export async function favoriteProjectClip(
  projectId: string,
  clipId: string,
  request: FavoriteClipRequest,
): Promise<ExportClipResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/favorite`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ExportClipResponse>;
}

export async function trimProjectClip(
  projectId: string,
  clipId: string,
  request: TrimClipRequest,
): Promise<ExportClipResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/trim`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ExportClipResponse>;
}

export async function deleteProjectClip(
  projectId: string,
  clipId: string,
): Promise<DeleteClipResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<DeleteClipResponse>;
}

export async function generateProjectClipCaptions(
  projectId: string,
  clipId: string,
): Promise<ClipCaptionsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions/generate`,
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipCaptionsResponse>;
}

export async function fetchProjectClipCaptions(
  projectId: string,
  clipId: string,
): Promise<ClipCaptionsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions`,
    {
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipCaptionsResponse>;
}

export async function updateProjectClipCaptions(
  projectId: string,
  clipId: string,
  request: UpdateCaptionsRequest,
): Promise<ClipCaptionsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipCaptionsResponse>;
}

export async function deleteProjectClipCaptions(
  projectId: string,
  clipId: string,
): Promise<DeleteCaptionsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<DeleteCaptionsResponse>;
}

export async function updateProjectClipCaptionStyle(
  projectId: string,
  clipId: string,
  request: UpdateCaptionStyleRequest,
): Promise<ClipCaptionsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions/style`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipCaptionsResponse>;
}

export async function resetProjectClipCaptionStyle(
  projectId: string,
  clipId: string,
): Promise<ClipCaptionsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions/style/reset`,
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ClipCaptionsResponse>;
}

export async function renderProjectClipCaptions(
  projectId: string,
  clipId: string,
): Promise<ExportClipResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/clips/${clipId}/captions/render`,
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    throw { message: await parseError(response), status: response.status } satisfies ApiError;
  }

  return response.json() as Promise<ExportClipResponse>;
}
