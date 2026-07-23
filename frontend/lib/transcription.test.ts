import { describe, expect, it } from "vitest";
import {
  qualityRatingLabel,
  sanitizeVocabularyHints,
  TRANSCRIPTION_QUALITY_MODES,
  validateRetranscribeRange,
} from "@/lib/transcription";

describe("transcription helpers", () => {
  it("lists all quality modes", () => {
    expect(TRANSCRIPTION_QUALITY_MODES.map((mode) => mode.value)).toEqual([
      "fast",
      "balanced",
      "high_accuracy",
    ]);
  });

  it("sanitizes vocabulary hints", () => {
    expect(sanitizeVocabularyHints("  Alice   Corp  ")).toBe("Alice Corp");
  });

  it("validates retranscribe range", () => {
    expect(validateRetranscribeRange(0, 2, 10)).toBeNull();
    expect(validateRetranscribeRange(2, 1, 10)).toContain("after start");
    expect(validateRetranscribeRange(-1, 2, 10)).toContain("non-negative");
  });

  it("labels quality ratings", () => {
    expect(qualityRatingLabel("good")).toBe("Good");
    expect(qualityRatingLabel("review_recommended")).toBe("Review recommended");
  });
});
