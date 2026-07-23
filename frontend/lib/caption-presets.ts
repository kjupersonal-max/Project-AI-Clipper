import type { CaptionStyle } from "@/lib/caption-style";
import { markCaptionStyleCustom } from "@/lib/caption-style";

export type CaptionPresetStyle = Omit<CaptionStyle, "preset_id">;

export type CaptionPreset = {
  id: string;
  name: string;
  is_builtin: boolean;
  is_default: boolean;
  style: CaptionPresetStyle;
  created_at: string;
  updated_at: string;
};

export type CaptionPresetListResponse = {
  presets: CaptionPreset[];
  default_preset_id: string | null;
};

export type CaptionPresetExportPayload = {
  schema_version: number;
  preset: {
    name: string;
    style: CaptionPresetStyle;
  };
};

export type CaptionPresetImportPayload = {
  schema_version: number;
  preset?: {
    name: string;
    style: CaptionPresetStyle;
  };
  presets?: Array<{
    name: string;
    style: CaptionPresetStyle;
  }>;
};

export const CAPTION_PRESET_SCHEMA_VERSION = 1;

export function captionPresetStyleToCaptionStyle(style: CaptionPresetStyle): CaptionStyle {
  return markCaptionStyleCustom({
    preset_id: "custom",
    ...style,
  });
}

export function captionStyleToPresetStyle(style: CaptionStyle): CaptionPresetStyle {
  const { preset_id, ...rest } = style;
  void preset_id;
  return rest;
}

export function presetStylesEqual(left: CaptionPresetStyle, right: CaptionPresetStyle): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function buildPresetPreviewCss(style: CaptionPresetStyle): Record<string, string | number> {
  const css: Record<string, string | number> = {
    color: style.text_color,
    fontFamily: style.font_family,
    fontSize: `${Math.max(10, Math.min(style.font_size, 18))}px`,
    fontWeight: style.font_weight,
    textAlign: style.text_alignment,
    textTransform: style.text_transform === "none" ? "none" : style.text_transform,
    backgroundColor:
      style.background_opacity > 0
        ? `${style.background_color}${Math.round(style.background_opacity * 255)
            .toString(16)
            .padStart(2, "0")}`
        : "transparent",
  };
  if (style.outline_width > 0) {
    css.WebkitTextStroke = `${Math.min(style.outline_width, 2)}px ${style.outline_color}`;
  }
  return css;
}
