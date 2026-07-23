import type { CaptionSegment, CaptionWord } from "@/lib/clip-captions";

export type CaptionStylePresetId =
  | "clean-minimal"
  | "bold-pop"
  | "podcast"
  | "karaoke-highlight"
  | "high-contrast"
  | "creator-subtitle"
  | "custom";

export type CaptionTextAlignment = "left" | "center" | "right";
export type CaptionTextTransform = "none" | "uppercase" | "lowercase";
export type CaptionAnimationType =
  | "none"
  | "fade"
  | "pop"
  | "scale"
  | "slide-up"
  | "bounce"
  | "active-word-emphasis";
export type CaptionWordsPerGroup = "1" | "2" | "3" | "4" | "full";
export type CaptionSafeAreaMode = "none" | "tiktok" | "youtube-shorts" | "generic";

export type CaptionStyle = {
  preset_id: CaptionStylePresetId;
  font_family: string;
  font_size: number;
  font_weight: number;
  text_color: string;
  active_word_color: string;
  outline_color: string;
  outline_width: number;
  background_color: string;
  background_opacity: number;
  shadow_enabled: boolean;
  shadow_strength: number;
  text_alignment: CaptionTextAlignment;
  horizontal_position: number;
  vertical_position: number;
  max_line_width: number;
  words_per_group: CaptionWordsPerGroup;
  text_transform: CaptionTextTransform;
  animation_type: CaptionAnimationType;
  animation_intensity: number;
  safe_area_mode: CaptionSafeAreaMode;
};

export type CaptionWordGroup = {
  words: CaptionWord[];
  text: string;
  start: number;
  end: number;
};

export type CaptionDisplayState = {
  segment: CaptionSegment;
  group: CaptionWordGroup | null;
  activeWordIndex: number | null;
  displayText: string;
};

export const CAPTION_FONT_OPTIONS = [
  "Inter, system-ui, sans-serif",
  "Arial, Helvetica, sans-serif",
  "Georgia, serif",
  "Impact, Haettenschweiler, sans-serif",
  "Courier New, monospace",
  "Verdana, Geneva, sans-serif",
] as const;

export const CAPTION_STYLE_PRESETS: Record<
  Exclude<CaptionStylePresetId, "custom">,
  { label: string; style: Omit<CaptionStyle, "preset_id"> }
> = {
  "clean-minimal": {
    label: "Clean Minimal",
    style: {
      font_family: "Inter, system-ui, sans-serif",
      font_size: 22,
      font_weight: 600,
      text_color: "#FFFFFF",
      active_word_color: "#FFFFFF",
      outline_color: "#000000",
      outline_width: 1,
      background_color: "#000000",
      background_opacity: 0.45,
      shadow_enabled: false,
      shadow_strength: 0,
      text_alignment: "center",
      horizontal_position: 50,
      vertical_position: 88,
      max_line_width: 85,
      words_per_group: "full",
      text_transform: "none",
      animation_type: "fade",
      animation_intensity: 0.4,
      safe_area_mode: "none",
    },
  },
  "bold-pop": {
    label: "Bold Pop",
    style: {
      font_family: "Impact, Haettenschweiler, sans-serif",
      font_size: 32,
      font_weight: 800,
      text_color: "#FFFFFF",
      active_word_color: "#FF6B6B",
      outline_color: "#000000",
      outline_width: 3,
      background_color: "#000000",
      background_opacity: 0,
      shadow_enabled: true,
      shadow_strength: 0.7,
      text_alignment: "center",
      horizontal_position: 50,
      vertical_position: 75,
      max_line_width: 90,
      words_per_group: "2",
      text_transform: "uppercase",
      animation_type: "pop",
      animation_intensity: 0.7,
      safe_area_mode: "none",
    },
  },
  podcast: {
    label: "Podcast",
    style: {
      font_family: "Georgia, serif",
      font_size: 20,
      font_weight: 500,
      text_color: "#F5F5F5",
      active_word_color: "#F5F5F5",
      outline_color: "#1A1A1A",
      outline_width: 0,
      background_color: "#1A1A1A",
      background_opacity: 0.75,
      shadow_enabled: false,
      shadow_strength: 0,
      text_alignment: "left",
      horizontal_position: 50,
      vertical_position: 85,
      max_line_width: 88,
      words_per_group: "full",
      text_transform: "none",
      animation_type: "fade",
      animation_intensity: 0.3,
      safe_area_mode: "none",
    },
  },
  "karaoke-highlight": {
    label: "Karaoke Highlight",
    style: {
      font_family: "Arial, Helvetica, sans-serif",
      font_size: 28,
      font_weight: 700,
      text_color: "#CCCCCC",
      active_word_color: "#00FF88",
      outline_color: "#000000",
      outline_width: 2,
      background_color: "#000000",
      background_opacity: 0.3,
      shadow_enabled: true,
      shadow_strength: 0.4,
      text_alignment: "center",
      horizontal_position: 50,
      vertical_position: 80,
      max_line_width: 92,
      words_per_group: "3",
      text_transform: "none",
      animation_type: "active-word-emphasis",
      animation_intensity: 0.8,
      safe_area_mode: "none",
    },
  },
  "high-contrast": {
    label: "High Contrast",
    style: {
      font_family: "Arial, Helvetica, sans-serif",
      font_size: 26,
      font_weight: 800,
      text_color: "#FFFF00",
      active_word_color: "#FFFFFF",
      outline_color: "#000000",
      outline_width: 4,
      background_color: "#000000",
      background_opacity: 0.85,
      shadow_enabled: true,
      shadow_strength: 0.6,
      text_alignment: "center",
      horizontal_position: 50,
      vertical_position: 85,
      max_line_width: 90,
      words_per_group: "full",
      text_transform: "uppercase",
      animation_type: "none",
      animation_intensity: 0.5,
      safe_area_mode: "none",
    },
  },
  "creator-subtitle": {
    label: "Creator Subtitle",
    style: {
      font_family: "Verdana, Geneva, sans-serif",
      font_size: 24,
      font_weight: 700,
      text_color: "#FFFFFF",
      active_word_color: "#4FC3F7",
      outline_color: "#000000",
      outline_width: 2,
      background_color: "#000000",
      background_opacity: 0.5,
      shadow_enabled: true,
      shadow_strength: 0.5,
      text_alignment: "center",
      horizontal_position: 50,
      vertical_position: 82,
      max_line_width: 88,
      words_per_group: "4",
      text_transform: "none",
      animation_type: "slide-up",
      animation_intensity: 0.5,
      safe_area_mode: "none",
    },
  },
};

export function createDefaultCaptionStyle(): CaptionStyle {
  return {
    preset_id: "clean-minimal",
    ...CAPTION_STYLE_PRESETS["clean-minimal"].style,
  };
}

export function cloneCaptionStyle(style: CaptionStyle): CaptionStyle {
  return { ...style };
}

export function applyCaptionPreset(presetId: Exclude<CaptionStylePresetId, "custom">): CaptionStyle {
  const preset = CAPTION_STYLE_PRESETS[presetId];
  return {
    preset_id: presetId,
    ...preset.style,
  };
}

export function markCaptionStyleCustom(style: CaptionStyle): CaptionStyle {
  return {
    ...style,
    preset_id: "custom",
  };
}

export function groupCaptionWords(
  segment: CaptionSegment,
  wordsPerGroup: CaptionWordsPerGroup,
): CaptionWordGroup[] {
  if (wordsPerGroup === "full" || segment.words.length === 0) {
    return [
      {
        words: segment.words,
        text: segment.text,
        start: segment.start,
        end: segment.end,
      },
    ];
  }

  const chunkSize = Number(wordsPerGroup);
  const groups: CaptionWordGroup[] = [];

  for (let index = 0; index < segment.words.length; index += chunkSize) {
    const words = segment.words.slice(index, index + chunkSize);
    groups.push({
      words,
      text: words.map((word) => word.word).join(" "),
      start: words[0].start,
      end: words[words.length - 1].end,
    });
  }

  return groups.length > 0
    ? groups
    : [
        {
          words: [],
          text: segment.text,
          start: segment.start,
          end: segment.end,
        },
      ];
}

export function findActiveWordIndex(words: CaptionWord[], currentTime: number): number | null {
  if (words.length === 0) {
    return null;
  }

  const index = words.findIndex(
    (word) => currentTime >= word.start && currentTime < word.end,
  );
  return index >= 0 ? index : null;
}

export function findActiveWordGroup(
  groups: CaptionWordGroup[],
  currentTime: number,
): CaptionWordGroup | null {
  return (
    groups.find((group) => currentTime >= group.start && currentTime < group.end) ?? null
  );
}

export function resolveCaptionDisplayState(
  segment: CaptionSegment,
  currentTime: number,
  wordsPerGroup: CaptionWordsPerGroup,
): CaptionDisplayState {
  const groups = groupCaptionWords(segment, wordsPerGroup);
  const group = findActiveWordGroup(groups, currentTime) ?? groups[0] ?? null;
  const activeWordIndex =
    group && group.words.length > 0 ? findActiveWordIndex(group.words, currentTime) : null;

  return {
    segment,
    group,
    activeWordIndex,
    displayText: group?.text ?? segment.text,
  };
}

export function applyTextTransform(text: string, transform: CaptionTextTransform): string {
  switch (transform) {
    case "uppercase":
      return text.toUpperCase();
    case "lowercase":
      return text.toLowerCase();
    default:
      return text;
  }
}

export function buildCaptionStyleCss(style: CaptionStyle): Record<string, string | number> {
  const shadowAlpha = style.shadow_enabled ? style.shadow_strength * 0.6 : 0;
  const backgroundAlpha = style.background_opacity;

  const hexToRgba = (hex: string, alpha: number) => {
    const normalized = hex.replace("#", "");
    if (normalized.length !== 6) {
      return `rgba(0, 0, 0, ${alpha})`;
    }
    const red = parseInt(normalized.slice(0, 2), 16);
    const green = parseInt(normalized.slice(2, 4), 16);
    const blue = parseInt(normalized.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  };

  const outlineShadow =
    style.outline_width > 0
      ? [
          `${style.outline_width}px ${style.outline_width}px 0 ${style.outline_color}`,
          `-${style.outline_width}px ${style.outline_width}px 0 ${style.outline_color}`,
          `${style.outline_width}px -${style.outline_width}px 0 ${style.outline_color}`,
          `-${style.outline_width}px -${style.outline_width}px 0 ${style.outline_color}`,
        ].join(", ")
      : undefined;

  const dropShadow = style.shadow_enabled
    ? `0 2px ${4 + style.shadow_strength * 8}px rgba(0, 0, 0, ${shadowAlpha})`
    : undefined;

  const textShadow = [outlineShadow, dropShadow].filter(Boolean).join(", ") || undefined;

  const css: Record<string, string | number> = {
    fontFamily: style.font_family,
    fontSize: `${style.font_size}px`,
    fontWeight: style.font_weight,
    color: style.text_color,
    textAlign: style.text_alignment,
    maxWidth: `${style.max_line_width}%`,
    backgroundColor: hexToRgba(style.background_color, backgroundAlpha),
    lineHeight: 1.25,
  };

  if (textShadow) {
    css.textShadow = textShadow;
  }

  return css;
}

export function getCaptionAnimationClassName(
  animationType: CaptionAnimationType,
  intensity: number,
  reducedMotion: boolean,
): string {
  if (reducedMotion || animationType === "none") {
    return "caption-anim-none";
  }

  const intensityClass =
    intensity >= 0.66 ? "caption-anim-strong" : intensity >= 0.33 ? "caption-anim-medium" : "caption-anim-soft";

  switch (animationType) {
    case "fade":
      return `caption-anim-fade ${intensityClass}`;
    case "pop":
      return `caption-anim-pop ${intensityClass}`;
    case "scale":
      return `caption-anim-scale ${intensityClass}`;
    case "slide-up":
      return `caption-anim-slide-up ${intensityClass}`;
    case "bounce":
      return `caption-anim-bounce ${intensityClass}`;
    case "active-word-emphasis":
      return `caption-anim-active-word ${intensityClass}`;
    default:
      return "caption-anim-none";
  }
}

export function buildCaptionStyleUpdatePayload(style: CaptionStyle): CaptionStyle {
  return cloneCaptionStyle(style);
}
