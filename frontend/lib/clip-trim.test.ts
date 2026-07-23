import { describe, expect, it } from "vitest";
import {
  clampPlaybackTime,
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

describe("clip trim helpers", () => {
  it("formats and parses trim timestamps", () => {
    expect(formatTrimTimestamp(72.5)).toBe("1:12.500");
    expect(parseTrimTimestamp("1:12.500")).toBeCloseTo(72.5);
    expect(parseTrimTimestamp("4.25")).toBeCloseTo(4.25);
  });

  it("computes frame step from frame rate", () => {
    expect(getFrameStep(30)).toBeCloseTo(1 / 30);
    expect(getFrameStep(null)).toBeCloseTo(1 / 30);
  });

  it("steps trim time by frames", () => {
    expect(stepTrimTime(1.0, 1, 30)).toBeCloseTo(1 + 1 / 30);
  });

  it("normalizes trim range within bounds", () => {
    const bounds = getTrimBounds(10, 20);
    const normalized = normalizeTrimRange(10.5, 19.5, bounds);
    expect(normalized.startTime).toBeCloseTo(10.5);
    expect(normalized.endTime).toBeCloseTo(19.5);
  });

  it("validates end before start", () => {
    const bounds = getTrimBounds(0, 10);
    expect(validateTrimRange(5, 4, bounds)).toMatch(/after start time/i);
  });

  it("derives trimmed clip names", () => {
    expect(deriveTrimmedClipName("Sample clip", "sample.mp4")).toBe("Sample clip (trimmed)");
  });

  it("clamps playback time to trim window", () => {
    expect(clampPlaybackTime(15, 10, 12)).toBe(12);
    expect(computeTrimDuration(10, 12.5)).toBeCloseTo(2.5);
  });
});
