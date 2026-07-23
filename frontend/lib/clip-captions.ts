const MIN_CAPTION_DURATION_SECONDS = 0.05;

export type CaptionWord = {
  word: string;
  start: number;
  end: number;
};

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

export type ClipCaptions = {
  project_id: string;
  clip_id: string;
  source_start_time: number;
  source_end_time: number;
  duration: number;
  candidate_id: string | null;
  segments: CaptionSegment[];
  created_at: string;
  updated_at: string;
};

export function findActiveCaption(
  segments: CaptionSegment[],
  currentTime: number,
): CaptionSegment | null {
  return (
    segments.find(
      (segment) => currentTime >= segment.start && currentTime < segment.end,
    ) ?? null
  );
}

export function validateCaptionSegment(
  segment: Pick<CaptionSegment, "start" | "end" | "text">,
  clipDuration: number,
): string | null {
  if (segment.start < 0) {
    return "Start time must be non-negative.";
  }

  if (segment.end <= segment.start) {
    return "End time must be after start time.";
  }

  if (segment.end - segment.start < MIN_CAPTION_DURATION_SECONDS) {
    return "Caption duration is too short.";
  }

  if (segment.end > clipDuration + 0.001) {
    return "Caption end time exceeds clip duration.";
  }

  return null;
}

export function validateCaptionSegments(
  segments: CaptionSegment[],
  clipDuration: number,
): string | null {
  for (const segment of segments) {
    const error = validateCaptionSegment(segment, clipDuration);
    if (error) {
      return error;
    }
  }

  return null;
}

export function sortCaptionSegments(segments: CaptionSegment[]): CaptionSegment[] {
  return [...segments].sort((left, right) => left.sequence - right.sequence);
}

export function formatCaptionTimestamp(seconds: number): string {
  const safeSeconds = Math.max(0, seconds);
  const minutes = Math.floor(safeSeconds / 60);
  const remaining = safeSeconds - minutes * 60;
  return `${minutes}:${remaining.toFixed(3).padStart(6, "0")}`;
}

export function parseCaptionTimestamp(value: string): number | null {
  const trimmed = value.trim();
  const match = /^(\d+):(\d+(?:\.\d+)?)$/.exec(trimmed);
  if (!match) {
    return null;
  }

  const minutes = Number(match[1]);
  const seconds = Number(match[2]);
  if (!Number.isFinite(minutes) || !Number.isFinite(seconds) || seconds >= 60) {
    return null;
  }

  return minutes * 60 + seconds;
}

export function buildCaptionUpdatePayload(segments: CaptionSegment[]) {
  return sortCaptionSegments(segments).map((segment, index) => ({
    id: segment.id,
    text: segment.text,
    start: segment.start,
    end: segment.end,
    words: segment.words,
    sequence: index,
  }));
}

export function cloneCaptionSegments(segments: CaptionSegment[]): CaptionSegment[] {
  return segments.map((segment) => ({
    ...segment,
    words: segment.words.map((word) => ({ ...word })),
  }));
}
