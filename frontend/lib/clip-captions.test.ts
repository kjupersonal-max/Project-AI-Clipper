import { describe, expect, it } from "vitest";
import {
  buildCaptionUpdatePayload,
  findActiveCaption,
  formatCaptionTimestamp,
  parseCaptionTimestamp,
  validateCaptionSegment,
  validateCaptionSegments,
  type CaptionSegment,
} from "@/lib/clip-captions";

const sampleSegments: CaptionSegment[] = [
  {
    id: "cap-1",
    text: "Hello",
    start: 0,
    end: 1.5,
    words: [],
    sequence: 0,
    created_at: "2026-07-22T18:00:00Z",
    updated_at: "2026-07-22T18:00:00Z",
  },
  {
    id: "cap-2",
    text: "World",
    start: 1.5,
    end: 3,
    words: [],
    sequence: 1,
    created_at: "2026-07-22T18:00:00Z",
    updated_at: "2026-07-22T18:00:00Z",
  },
];

describe("clip-captions helpers", () => {
  it("finds the active caption during playback", () => {
    expect(findActiveCaption(sampleSegments, 0.5)?.id).toBe("cap-1");
    expect(findActiveCaption(sampleSegments, 2)?.id).toBe("cap-2");
    expect(findActiveCaption(sampleSegments, 3)).toBeNull();
  });

  it("validates caption timing against clip duration", () => {
    expect(validateCaptionSegment({ text: "Ok", start: 0, end: 1 }, 4)).toBeNull();
    expect(validateCaptionSegment({ text: "Bad", start: 2, end: 1 }, 4)).toMatch(
      /after start/i,
    );
    expect(validateCaptionSegments(sampleSegments, 2.5)).toMatch(/exceeds clip duration/i);
  });

  it("formats and parses caption timestamps", () => {
    expect(formatCaptionTimestamp(65.5)).toBe("1:05.500");
    expect(parseCaptionTimestamp("1:05.500")).toBe(65.5);
    expect(parseCaptionTimestamp("bad")).toBeNull();
  });

  it("builds update payload with sequential order", () => {
    expect(buildCaptionUpdatePayload([sampleSegments[1], sampleSegments[0]])).toEqual([
      expect.objectContaining({ id: "cap-1", sequence: 0 }),
      expect.objectContaining({ id: "cap-2", sequence: 1 }),
    ]);
  });
});
