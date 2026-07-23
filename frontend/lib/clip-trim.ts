export const DEFAULT_FRAME_RATE = 30;
export const MIN_TRIM_DURATION_SECONDS = 0.1;

export type TrimBounds = {
  minStart: number;
  maxEnd: number;
};

export function getFrameStep(frameRate: number | null | undefined): number {
  const safeRate = frameRate && frameRate > 0 ? frameRate : DEFAULT_FRAME_RATE;
  return 1 / safeRate;
}

export function stepTrimTime(
  time: number,
  frames: number,
  frameRate: number | null | undefined,
): number {
  return time + frames * getFrameStep(frameRate);
}

export function clampTrimTime(time: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, time));
}

export function computeTrimDuration(startTime: number, endTime: number): number {
  return Math.max(0, endTime - startTime);
}

export function formatTrimTimestamp(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const remaining = safe - minutes * 60;
  return `${minutes}:${remaining.toFixed(3).padStart(6, "0")}`;
}

export function parseTrimTimestamp(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  if (trimmed.includes(":")) {
    const [minutesPart, secondsPart] = trimmed.split(":");
    const minutes = Number(minutesPart);
    const seconds = Number(secondsPart);
    if (!Number.isFinite(minutes) || !Number.isFinite(seconds)) {
      return null;
    }
    return minutes * 60 + seconds;
  }

  const numeric = Number(trimmed);
  return Number.isFinite(numeric) ? numeric : null;
}

export function getTrimBounds(clipStart: number, clipEnd: number): TrimBounds {
  return {
    minStart: clipStart,
    maxEnd: clipEnd,
  };
}

export function normalizeTrimRange(
  startTime: number,
  endTime: number,
  bounds: TrimBounds,
): { startTime: number; endTime: number } {
  let nextStart = clampTrimTime(startTime, bounds.minStart, bounds.maxEnd);
  let nextEnd = clampTrimTime(endTime, bounds.minStart, bounds.maxEnd);

  if (nextEnd <= nextStart) {
    nextEnd = Math.min(bounds.maxEnd, nextStart + MIN_TRIM_DURATION_SECONDS);
  }

  if (nextEnd - nextStart < MIN_TRIM_DURATION_SECONDS) {
    nextStart = Math.max(bounds.minStart, nextEnd - MIN_TRIM_DURATION_SECONDS);
  }

  return {
    startTime: clampTrimTime(nextStart, bounds.minStart, bounds.maxEnd - MIN_TRIM_DURATION_SECONDS),
    endTime: clampTrimTime(nextEnd, bounds.minStart + MIN_TRIM_DURATION_SECONDS, bounds.maxEnd),
  };
}

export function validateTrimRange(
  startTime: number,
  endTime: number,
  bounds: TrimBounds,
): string | null {
  if (startTime < bounds.minStart) {
    return `Start time cannot be earlier than ${formatTrimTimestamp(bounds.minStart)}.`;
  }

  if (endTime > bounds.maxEnd) {
    return `End time cannot be later than ${formatTrimTimestamp(bounds.maxEnd)}.`;
  }

  if (endTime <= startTime) {
    return "End time must be after start time.";
  }

  if (computeTrimDuration(startTime, endTime) < MIN_TRIM_DURATION_SECONDS) {
    return "Trimmed clip must be longer than zero.";
  }

  return null;
}

export function deriveTrimmedClipName(sourceName: string | null | undefined, filename: string): string {
  const trimmedName = sourceName?.trim();
  const base = trimmedName || filename.replace(/\.mp4$/i, "");
  return `${base} (trimmed)`;
}

export function isPlaybackWithinTrim(
  currentTime: number,
  startTime: number,
  endTime: number,
): boolean {
  return currentTime >= startTime && currentTime <= endTime;
}

export function clampPlaybackTime(
  currentTime: number,
  startTime: number,
  endTime: number,
): number {
  return clampTrimTime(currentTime, startTime, endTime);
}
