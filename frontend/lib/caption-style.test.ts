import { describe, expect, it } from "vitest";
import {
  applyCaptionPreset,
  applyTextTransform,
  createDefaultCaptionStyle,
  getCaptionAnimationClassName,
  groupCaptionWords,
  resolveCaptionDisplayState,
} from "@/lib/caption-style";
import type { CaptionSegment } from "@/lib/clip-captions";

const wordSegment: CaptionSegment = {
  id: "cap-words",
  text: "Hello beautiful world today",
  start: 0,
  end: 4,
  words: [
    { word: "Hello", start: 0, end: 0.8 },
    { word: "beautiful", start: 0.8, end: 1.6 },
    { word: "world", start: 1.6, end: 2.4 },
    { word: "today", start: 2.4, end: 4 },
  ],
  sequence: 0,
  created_at: "2026-07-22T18:00:00Z",
  updated_at: "2026-07-22T18:00:00Z",
};

const segmentOnly: CaptionSegment = {
  id: "cap-segment",
  text: "Segment only caption",
  start: 0,
  end: 2,
  words: [],
  sequence: 0,
  created_at: "2026-07-22T18:00:00Z",
  updated_at: "2026-07-22T18:00:00Z",
};

describe("caption-style helpers", () => {
  it("creates default style", () => {
    const style = createDefaultCaptionStyle();
    expect(style.preset_id).toBe("clean-minimal");
    expect(style.font_size).toBe(22);
  });

  it("applies presets", () => {
    const style = applyCaptionPreset("bold-pop");
    expect(style.preset_id).toBe("bold-pop");
    expect(style.text_transform).toBe("uppercase");
  });

  it("groups words into configurable chunks", () => {
    const groups = groupCaptionWords(wordSegment, "2");
    expect(groups).toHaveLength(2);
    expect(groups[0].text).toBe("Hello beautiful");
    expect(groups[1].text).toBe("world today");
  });

  it("falls back to full segment when no word timing exists", () => {
    const groups = groupCaptionWords(segmentOnly, "2");
    expect(groups).toHaveLength(1);
    expect(groups[0].text).toBe("Segment only caption");
  });

  it("highlights active word when word timing exists", () => {
    const state = resolveCaptionDisplayState(wordSegment, 1.0, "2");
    expect(state.activeWordIndex).toBe(1);
    expect(state.group?.text).toBe("Hello beautiful");
  });

  it("returns null active word for segment-only captions", () => {
    const state = resolveCaptionDisplayState(segmentOnly, 1.0, "full");
    expect(state.activeWordIndex).toBeNull();
    expect(state.displayText).toBe("Segment only caption");
  });

  it("maps animation types to css classes", () => {
    expect(getCaptionAnimationClassName("pop", 0.8, false)).toContain("caption-anim-pop");
    expect(getCaptionAnimationClassName("fade", 0.2, true)).toBe("caption-anim-none");
  });

  it("applies text transforms", () => {
    expect(applyTextTransform("Hello", "uppercase")).toBe("HELLO");
    expect(applyTextTransform("Hello", "lowercase")).toBe("hello");
  });
});
