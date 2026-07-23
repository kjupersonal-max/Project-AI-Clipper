"use client";

import {
  applyCaptionPreset,
  CAPTION_FONT_OPTIONS,
  CAPTION_STYLE_PRESETS,
  cloneCaptionStyle,
  markCaptionStyleCustom,
  type CaptionAnimationType,
  type CaptionSafeAreaMode,
  type CaptionStyle,
  type CaptionStylePresetId,
  type CaptionTextAlignment,
  type CaptionWordsPerGroup,
} from "@/lib/caption-style";
import { cn } from "@/lib/utils";
import { Palette, RotateCcw, Save } from "lucide-react";

type CaptionStylePanelProps = {
  style: CaptionStyle;
  dirty: boolean;
  saving?: boolean;
  resetting?: boolean;
  disabled?: boolean;
  showSafeAreaGuides: boolean;
  onStyleChange: (style: CaptionStyle) => void;
  onShowSafeAreaGuidesChange: (show: boolean) => void;
  onSave: () => void;
  onReset: () => void;
};

const PRESET_OPTIONS = Object.entries(CAPTION_STYLE_PRESETS).map(([id, preset]) => ({
  id: id as Exclude<CaptionStylePresetId, "custom">,
  label: preset.label,
}));

const ANIMATION_OPTIONS: { value: CaptionAnimationType; label: string }[] = [
  { value: "none", label: "None" },
  { value: "fade", label: "Fade" },
  { value: "pop", label: "Pop" },
  { value: "scale", label: "Scale" },
  { value: "slide-up", label: "Slide up" },
  { value: "bounce", label: "Bounce" },
  { value: "active-word-emphasis", label: "Active word emphasis" },
];

const WORDS_PER_GROUP_OPTIONS: { value: CaptionWordsPerGroup; label: string }[] = [
  { value: "1", label: "1 word" },
  { value: "2", label: "2 words" },
  { value: "3", label: "3 words" },
  { value: "4", label: "4 words" },
  { value: "full", label: "Full segment" },
];

const SAFE_AREA_OPTIONS: { value: CaptionSafeAreaMode; label: string }[] = [
  { value: "none", label: "None" },
  { value: "tiktok", label: "TikTok guide" },
  { value: "youtube-shorts", label: "YouTube Shorts guide" },
  { value: "generic", label: "Generic safe area" },
];

const ALIGNMENT_OPTIONS: { value: CaptionTextAlignment; label: string }[] = [
  { value: "left", label: "Left" },
  { value: "center", label: "Center" },
  { value: "right", label: "Right" },
];

function updateStyle(
  current: CaptionStyle,
  patch: Partial<CaptionStyle>,
  onStyleChange: (style: CaptionStyle) => void,
) {
  onStyleChange(markCaptionStyleCustom({ ...current, ...patch }));
}

export function CaptionStylePanel({
  style,
  dirty,
  saving = false,
  resetting = false,
  disabled = false,
  showSafeAreaGuides,
  onStyleChange,
  onShowSafeAreaGuidesChange,
  onSave,
  onReset,
}: CaptionStylePanelProps) {
  const isBusy = disabled || saving || resetting;

  return (
    <div className="flex flex-col rounded-lg border border-zinc-800 bg-zinc-950/60">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
          <Palette className="h-4 w-4 text-sky-300" />
          Caption style
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onReset}
            disabled={isBusy}
            aria-label="Reset style"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 text-xs text-zinc-300 disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset style
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={isBusy || !dirty}
            aria-label="Save style"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 text-xs font-medium text-emerald-100 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            Save style
          </button>
        </div>
      </div>

      <div className="grid flex-1 gap-4 overflow-y-auto p-4 sm:grid-cols-2">
        <label className="space-y-1 sm:col-span-2">
          <span className="text-xs text-zinc-500">Preset</span>
          <select
            aria-label="Caption preset"
            value={style.preset_id === "custom" ? "" : style.preset_id}
            disabled={isBusy}
            onChange={(event) => {
              const value = event.target.value as Exclude<CaptionStylePresetId, "custom">;
              if (value) {
                onStyleChange(applyCaptionPreset(value));
              }
            }}
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          >
            <option value="">{style.preset_id === "custom" ? "Custom" : "Select preset"}</option>
            {PRESET_OPTIONS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Font</span>
          <select
            aria-label="Caption font"
            value={style.font_family}
            disabled={isBusy}
            onChange={(event) => updateStyle(style, { font_family: event.target.value }, onStyleChange)}
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          >
            {CAPTION_FONT_OPTIONS.map((font) => (
              <option key={font} value={font}>
                {font.split(",")[0]}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Font size ({style.font_size}px)</span>
          <input
            aria-label="Caption font size"
            type="range"
            min={12}
            max={72}
            step={1}
            value={style.font_size}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { font_size: Number(event.target.value) }, onStyleChange)
            }
            className="w-full"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Text color</span>
          <input
            aria-label="Caption text color"
            type="color"
            value={style.text_color}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { text_color: event.target.value }, onStyleChange)
            }
            className="h-9 w-full cursor-pointer rounded-md border border-zinc-800 bg-zinc-950"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Active word color</span>
          <input
            aria-label="Caption active word color"
            type="color"
            value={style.active_word_color}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { active_word_color: event.target.value }, onStyleChange)
            }
            className="h-9 w-full cursor-pointer rounded-md border border-zinc-800 bg-zinc-950"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Outline color</span>
          <input
            aria-label="Caption outline color"
            type="color"
            value={style.outline_color}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { outline_color: event.target.value }, onStyleChange)
            }
            className="h-9 w-full cursor-pointer rounded-md border border-zinc-800 bg-zinc-950"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Outline width ({style.outline_width}px)</span>
          <input
            aria-label="Caption outline width"
            type="range"
            min={0}
            max={8}
            step={0.5}
            value={style.outline_width}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { outline_width: Number(event.target.value) }, onStyleChange)
            }
            className="w-full"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Background color</span>
          <input
            aria-label="Caption background color"
            type="color"
            value={style.background_color}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { background_color: event.target.value }, onStyleChange)
            }
            className="h-9 w-full cursor-pointer rounded-md border border-zinc-800 bg-zinc-950"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">
            Background opacity ({Math.round(style.background_opacity * 100)}%)
          </span>
          <input
            aria-label="Caption background opacity"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={style.background_opacity}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { background_opacity: Number(event.target.value) }, onStyleChange)
            }
            className="w-full"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Text alignment</span>
          <select
            aria-label="Caption text alignment"
            value={style.text_alignment}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(
                style,
                { text_alignment: event.target.value as CaptionTextAlignment },
                onStyleChange,
              )
            }
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          >
            {ALIGNMENT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">
            Horizontal position ({Math.round(style.horizontal_position)}%)
          </span>
          <input
            aria-label="Caption horizontal position"
            type="range"
            min={0}
            max={100}
            step={1}
            value={style.horizontal_position}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { horizontal_position: Number(event.target.value) }, onStyleChange)
            }
            className="w-full"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">
            Vertical position ({Math.round(style.vertical_position)}%)
          </span>
          <input
            aria-label="Caption vertical position"
            type="range"
            min={0}
            max={100}
            step={1}
            value={style.vertical_position}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { vertical_position: Number(event.target.value) }, onStyleChange)
            }
            className="w-full"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Words per group</span>
          <select
            aria-label="Caption words per group"
            value={style.words_per_group}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(
                style,
                { words_per_group: event.target.value as CaptionWordsPerGroup },
                onStyleChange,
              )
            }
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          >
            {WORDS_PER_GROUP_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Animation</span>
          <select
            aria-label="Caption animation"
            value={style.animation_type}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(
                style,
                { animation_type: event.target.value as CaptionAnimationType },
                onStyleChange,
              )
            }
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          >
            {ANIMATION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">
            Animation intensity ({Math.round(style.animation_intensity * 100)}%)
          </span>
          <input
            aria-label="Caption animation intensity"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={style.animation_intensity}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { animation_intensity: Number(event.target.value) }, onStyleChange)
            }
            className="w-full"
          />
        </label>

        <label className="space-y-1">
          <span className="text-xs text-zinc-500">Safe area guide</span>
          <select
            aria-label="Caption safe area mode"
            value={style.safe_area_mode}
            disabled={isBusy}
            onChange={(event) => {
              const safeAreaMode = event.target.value as CaptionSafeAreaMode;
              updateStyle(style, { safe_area_mode: safeAreaMode }, onStyleChange);
              onShowSafeAreaGuidesChange(safeAreaMode !== "none");
            }}
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          >
            {SAFE_AREA_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 sm:col-span-2">
          <input
            aria-label="Show safe area guides"
            type="checkbox"
            checked={showSafeAreaGuides}
            disabled={isBusy}
            onChange={(event) => onShowSafeAreaGuidesChange(event.target.checked)}
            className="rounded border-zinc-700"
          />
          <span className="text-xs text-zinc-400">Show safe-area preview guides on video</span>
        </label>

        <label className="flex items-center gap-2">
          <input
            aria-label="Caption shadow enabled"
            type="checkbox"
            checked={style.shadow_enabled}
            disabled={isBusy}
            onChange={(event) =>
              updateStyle(style, { shadow_enabled: event.target.checked }, onStyleChange)
            }
            className="rounded border-zinc-700"
          />
          <span className="text-xs text-zinc-400">Drop shadow</span>
        </label>

        {style.shadow_enabled ? (
          <label className="space-y-1">
            <span className="text-xs text-zinc-500">
              Shadow strength ({Math.round(style.shadow_strength * 100)}%)
            </span>
            <input
              aria-label="Caption shadow strength"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={style.shadow_strength}
              disabled={isBusy}
              onChange={(event) =>
                updateStyle(style, { shadow_strength: Number(event.target.value) }, onStyleChange)
              }
              className="w-full"
            />
          </label>
        ) : null}

        {dirty ? (
          <p className={cn("text-xs text-amber-300 sm:col-span-2")}>Unsaved style changes</p>
        ) : null}
      </div>
    </div>
  );
}

export { cloneCaptionStyle };
