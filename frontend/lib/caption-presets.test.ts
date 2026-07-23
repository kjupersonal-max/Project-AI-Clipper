import { describe, expect, it } from "vitest";
import {
  captionPresetStyleToCaptionStyle,
  captionStyleToPresetStyle,
  presetStylesEqual,
} from "@/lib/caption-presets";
import { createDefaultCaptionStyle } from "@/lib/caption-style";

describe("caption-presets helpers", () => {
  it("converts preset style to custom caption style", () => {
    const style = createDefaultCaptionStyle();
    const presetStyle = captionStyleToPresetStyle(style);
    const converted = captionPresetStyleToCaptionStyle({
      ...presetStyle,
      text_color: "#AABBCC",
    });
    expect(converted.preset_id).toBe("custom");
    expect(converted.text_color).toBe("#AABBCC");
  });

  it("compares preset styles", () => {
    const style = captionStyleToPresetStyle(createDefaultCaptionStyle());
    expect(presetStylesEqual(style, style)).toBe(true);
    expect(
      presetStylesEqual(style, {
        ...style,
        font_size: style.font_size + 1,
      }),
    ).toBe(false);
  });
});
