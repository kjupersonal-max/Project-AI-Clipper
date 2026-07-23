import type {
  TranscriptionQualityMode,
  TranscriptionQualityRating,
} from "@/lib/api/projects";

export const TRANSCRIPTION_QUALITY_MODES: {
  value: TranscriptionQualityMode;
  label: string;
  description: string;
  warning?: string;
}[] = [
  {
    value: "fast",
    label: "Fast",
    description: "Quick transcription with reasonable defaults.",
  },
  {
    value: "balanced",
    label: "Balanced",
    description: "Default mode with improved accuracy settings.",
  },
  {
    value: "high_accuracy",
    label: "High Accuracy",
    description: "Slower but better for unclear speech.",
    warning: "High accuracy mode is slower and uses more compute.",
  },
];

export function qualityRatingLabel(rating: TranscriptionQualityRating | null | undefined): string {
  switch (rating) {
    case "good":
      return "Good";
    case "review_recommended":
      return "Review recommended";
    case "poor":
      return "Poor";
    default:
      return "Unknown";
  }
}

export function qualityRatingClassName(
  rating: TranscriptionQualityRating | null | undefined,
): string {
  switch (rating) {
    case "good":
      return "text-emerald-300 border-emerald-500/30 bg-emerald-500/10";
    case "review_recommended":
      return "text-amber-200 border-amber-500/30 bg-amber-500/10";
    case "poor":
      return "text-red-300 border-red-500/30 bg-red-500/10";
    default:
      return "text-zinc-400 border-zinc-700 bg-zinc-900";
  }
}

export function sanitizeVocabularyHints(value: string, maxLength = 500): string {
  return value.trim().split(/\s+/).join(" ").slice(0, maxLength);
}

export function validateRetranscribeRange(
  start: number,
  end: number,
  clipDuration: number,
): string | null {
  if (start < 0) {
    return "Start time must be non-negative.";
  }
  if (end <= start) {
    return "End time must be after start time.";
  }
  if (end > clipDuration + 0.001) {
    return "Range must remain inside clip duration.";
  }
  return null;
}
