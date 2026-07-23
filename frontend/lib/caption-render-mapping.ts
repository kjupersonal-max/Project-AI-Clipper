import type { CaptionAnimationType } from "@/lib/caption-style";

export type ExportClipKind = "raw" | "captioned";

export const EXPORT_CLIP_KIND = {
  RAW: "raw",
  CAPTIONED: "captioned",
} as const satisfies Record<string, ExportClipKind>;

/**
 * Preview vs render parity notes for Phase 8 Part 3.
 * Safe-area guides are preview-only and never burned into exports.
 */
export const CAPTION_RENDER_PARITY = {
  exact: [
    "caption text and segment timing",
    "word grouping (1/2/3/4/full segment)",
    "text transform (none/uppercase/lowercase)",
    "font family mapping (first font in stack -> ASS font)",
    "text color, active-word color, outline color",
    "outline width, background color/opacity",
    "horizontal/vertical position (% based)",
    "text alignment",
    "maximum line width",
  ],
  approximate: [
    "font size (scaled from preview px to ASS PlayRes)",
    "fade animation (ASS \\fad timing approximates CSS fade)",
    "pop/scale (ASS \\fscx/\\fscy transform approximates CSS scale)",
    "slide up (ASS \\move approximates CSS translateY)",
    "bounce (chained \\move/\\t approximates CSS bounce)",
    "drop shadow depth (ASS Shadow field vs CSS text-shadow)",
    "active-word emphasis (ASS \\1c/\\t timed color vs CSS color+scale)",
  ],
  previewOnly: [
    "safe_area_mode guides (TikTok, YouTube Shorts, generic)",
    "show safe-area preview checkbox",
    "live CSS animation easing curves",
  ],
} as const;

export const CAPTION_ANIMATION_RENDER_MAP: Record<
  CaptionAnimationType,
  { ass: string; parity: "exact" | "approximate" | "none" }
> = {
  none: { ass: "none", parity: "exact" },
  fade: { ass: "\\fad", parity: "approximate" },
  pop: { ass: "\\fscx/\\fscy \\t", parity: "approximate" },
  scale: { ass: "\\fscx/\\fscy \\t", parity: "approximate" },
  "slide-up": { ass: "\\move", parity: "approximate" },
  bounce: { ass: "\\move + \\t", parity: "approximate" },
  "active-word-emphasis": { ass: "\\1c/\\t timed color", parity: "exact" },
};

export function isCaptionedExport(clip: { export_kind?: ExportClipKind | null }): boolean {
  return clip.export_kind === EXPORT_CLIP_KIND.CAPTIONED;
}

export function getCaptionedExportLabel(clip: {
  export_kind?: ExportClipKind | null;
  caption_style_preset?: string | null;
}): string | null {
  if (!isCaptionedExport(clip)) {
    return null;
  }
  const preset = clip.caption_style_preset?.replace(/-/g, " ");
  return preset ? `Captioned · ${preset}` : "Captioned export";
}
