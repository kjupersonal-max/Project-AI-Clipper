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

export function getProjectVideoUrl(projectId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/media/video`;
}
