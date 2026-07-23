"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createCaptionPreset,
  deleteCaptionPreset,
  duplicateCaptionPreset,
  exportCaptionPreset,
  fetchCaptionPresets,
  importCaptionPresets,
  updateCaptionPreset,
} from "@/lib/api/caption-presets";
import {
  buildPresetPreviewCss,
  captionPresetStyleToCaptionStyle,
  captionStyleToPresetStyle,
  presetStylesEqual,
  type CaptionPreset,
} from "@/lib/caption-presets";
import type { CaptionStyle } from "@/lib/caption-style";
import { cn } from "@/lib/utils";
import {
  Copy,
  Download,
  Loader2,
  Save,
  Star,
  Trash2,
  Upload,
  Wand2,
} from "lucide-react";

type CaptionPresetPanelProps = {
  currentStyle: CaptionStyle;
  disabled?: boolean;
  onApplyStyle: (style: CaptionStyle) => void;
  onError?: (message: string) => void;
};

export function CaptionPresetPanel({
  currentStyle,
  disabled = false,
  onApplyStyle,
  onError,
}: CaptionPresetPanelProps) {
  const [presets, setPresets] = useState<CaptionPreset[]>([]);
  const [defaultPresetId, setDefaultPresetId] = useState<string | null>(null);
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("");
  const inFlightRef = useRef(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  const selectedPreset = presets.find((preset) => preset.id === selectedPresetId) ?? null;
  const renameValue = renameDraft ?? selectedPreset?.name ?? "";
  const isBusy = disabled || loading || busyAction !== null;

  const reportError = useCallback(
    (error: unknown, fallback: string) => {
      const message =
        error && typeof error === "object" && "message" in error
          ? String((error as { message: string }).message)
          : fallback;
      onError?.(message);
    },
    [onError],
  );

  const loadPresets = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchCaptionPresets();
      setPresets(response.presets);
      setDefaultPresetId(response.default_preset_id);
      setSelectedPresetId((current) => current ?? response.default_preset_id);
    } catch (error) {
      reportError(error, "Unable to load caption presets.");
    } finally {
      setLoading(false);
    }
  }, [reportError]);

  /* eslint-disable react-hooks/set-state-in-effect -- preset catalog is loaded from API on mount */
  useEffect(() => {
    void loadPresets();
  }, [loadPresets]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleSelectPreset = useCallback((presetId: string) => {
    setSelectedPresetId(presetId);
    setRenameDraft(null);
  }, []);

  const runGuarded = useCallback(
    async (actionKey: string, task: () => Promise<void>) => {
      if (inFlightRef.current || isBusy) {
        return;
      }
      inFlightRef.current = true;
      setBusyAction(actionKey);
      try {
        await task();
      } finally {
        inFlightRef.current = false;
        setBusyAction(null);
      }
    },
    [isBusy],
  );

  const handleApply = useCallback(() => {
    if (!selectedPreset) {
      return;
    }
    onApplyStyle(captionPresetStyleToCaptionStyle(selectedPreset.style));
  }, [onApplyStyle, selectedPreset]);

  const handleSaveCurrent = useCallback(async () => {
    const trimmed = saveName.trim();
    if (!trimmed) {
      onError?.("Enter a name for the new preset.");
      return;
    }
    await runGuarded("save", async () => {
      try {
        const created = await createCaptionPreset({
          name: trimmed,
          style: captionStyleToPresetStyle(currentStyle),
        });
        await loadPresets();
        setSelectedPresetId(created.id);
        setSaveName("");
      } catch (error) {
        reportError(error, "Unable to save caption preset.");
      }
    });
  }, [currentStyle, loadPresets, onError, reportError, runGuarded, saveName]);

  const handleUpdateSelected = useCallback(async () => {
    if (!selectedPreset || selectedPreset.is_builtin) {
      return;
    }
    await runGuarded("update", async () => {
      try {
        await updateCaptionPreset(selectedPreset.id, {
          style: captionStyleToPresetStyle(currentStyle),
        });
        await loadPresets();
      } catch (error) {
        reportError(error, "Unable to update caption preset.");
      }
    });
  }, [currentStyle, loadPresets, reportError, runGuarded, selectedPreset]);

  const handleDuplicate = useCallback(async () => {
    if (!selectedPreset) {
      return;
    }
    await runGuarded("duplicate", async () => {
      try {
        const duplicated = await duplicateCaptionPreset(selectedPreset.id);
        await loadPresets();
        setSelectedPresetId(duplicated.id);
      } catch (error) {
        reportError(error, "Unable to duplicate caption preset.");
      }
    });
  }, [loadPresets, reportError, runGuarded, selectedPreset]);

  const handleRename = useCallback(async () => {
    if (!selectedPreset || selectedPreset.is_builtin) {
      return;
    }
    const trimmed = renameValue.trim();
    if (!trimmed) {
      onError?.("Preset name cannot be empty.");
      return;
    }
    await runGuarded("rename", async () => {
      try {
        await updateCaptionPreset(selectedPreset.id, { name: trimmed });
        await loadPresets();
      } catch (error) {
        reportError(error, "Unable to rename caption preset.");
      }
    });
  }, [loadPresets, onError, renameValue, reportError, runGuarded, selectedPreset]);

  const handleDelete = useCallback(async () => {
    if (!selectedPreset || selectedPreset.is_builtin || confirmDeleteId !== selectedPreset.id) {
      return;
    }
    await runGuarded("delete", async () => {
      try {
        await deleteCaptionPreset(selectedPreset.id);
        setConfirmDeleteId(null);
        setSelectedPresetId(defaultPresetId);
        await loadPresets();
      } catch (error) {
        reportError(error, "Unable to delete caption preset.");
      }
    });
  }, [confirmDeleteId, defaultPresetId, loadPresets, reportError, runGuarded, selectedPreset]);

  const handleSetDefault = useCallback(async () => {
    if (!selectedPreset) {
      return;
    }
    await runGuarded("default", async () => {
      try {
        await updateCaptionPreset(selectedPreset.id, { is_default: true });
        await loadPresets();
      } catch (error) {
        reportError(error, "Unable to set default caption preset.");
      }
    });
  }, [loadPresets, reportError, runGuarded, selectedPreset]);

  const handleExport = useCallback(async () => {
    if (!selectedPreset) {
      return;
    }
    await runGuarded("export", async () => {
      try {
        const payload = await exportCaptionPreset(selectedPreset.id);
        const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${selectedPreset.name.replace(/\s+/g, "-").toLowerCase()}-caption-preset.json`;
        anchor.click();
        URL.revokeObjectURL(url);
      } catch (error) {
        reportError(error, "Unable to export caption preset.");
      }
    });
  }, [reportError, runGuarded, selectedPreset]);

  const handleImportFile = useCallback(
    async (file: File) => {
      await runGuarded("import", async () => {
        try {
          const text = await file.text();
          const payload = JSON.parse(text) as {
            schema_version: number;
            preset?: { name: string; style: CaptionPreset["style"] };
            presets?: Array<{ name: string; style: CaptionPreset["style"] }>;
          };
          const result = await importCaptionPresets(payload);
          await loadPresets();
          if (result.imported[0]) {
            setSelectedPresetId(result.imported[0].id);
          }
        } catch (error) {
          reportError(error, "Unable to import caption preset JSON.");
        }
      });
    },
    [loadPresets, reportError, runGuarded],
  );

  const canUpdateSelected =
    selectedPreset &&
    !selectedPreset.is_builtin &&
    !presetStylesEqual(selectedPreset.style, captionStyleToPresetStyle(currentStyle));

  return (
    <div className="flex flex-col rounded-lg border border-zinc-800 bg-zinc-950/60">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
          <Wand2 className="h-4 w-4 text-violet-300" />
          Caption presets
        </div>
        {loading ? <Loader2 className="h-4 w-4 animate-spin text-zinc-500" /> : null}
      </div>

      <div className="space-y-4 p-4">
        <div className="grid max-h-56 gap-2 overflow-y-auto sm:grid-cols-2">
          {presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              disabled={isBusy}
              aria-label={`Preset ${preset.name}`}
              onClick={() => handleSelectPreset(preset.id)}
              className={cn(
                "rounded-lg border px-3 py-2 text-left transition-colors",
                selectedPresetId === preset.id
                  ? "border-violet-500/40 bg-violet-500/10"
                  : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-700",
              )}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium text-zinc-100">{preset.name}</span>
                <div className="flex shrink-0 items-center gap-1">
                  {preset.is_default ? (
                    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-200">
                      Default
                    </span>
                  ) : null}
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px]",
                      preset.is_builtin
                        ? "bg-sky-500/15 text-sky-200"
                        : "bg-emerald-500/15 text-emerald-200",
                    )}
                  >
                    {preset.is_builtin ? "Built-in" : "Custom"}
                  </span>
                </div>
              </div>
              <div
                className="truncate rounded px-2 py-1 text-xs"
                style={buildPresetPreviewCss(preset.style)}
              >
                Aa sample text
              </div>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={isBusy || !selectedPreset}
            onClick={handleApply}
            className="inline-flex h-8 items-center rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 text-xs font-medium text-violet-100 disabled:opacity-50"
          >
            Apply preset
          </button>
          <button
            type="button"
            disabled={isBusy || !selectedPreset}
            onClick={() => void handleSetDefault()}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-700 px-3 text-xs text-zinc-200 disabled:opacity-50"
          >
            <Star className="h-3.5 w-3.5" />
            Set default
          </button>
          <button
            type="button"
            disabled={isBusy || !selectedPreset}
            onClick={() => void handleDuplicate()}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-700 px-3 text-xs text-zinc-200 disabled:opacity-50"
          >
            <Copy className="h-3.5 w-3.5" />
            Duplicate
          </button>
          <button
            type="button"
            disabled={isBusy || !selectedPreset}
            onClick={() => void handleExport()}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-700 px-3 text-xs text-zinc-200 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            Export JSON
          </button>
          <button
            type="button"
            disabled={isBusy}
            onClick={() => importInputRef.current?.click()}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-700 px-3 text-xs text-zinc-200 disabled:opacity-50"
          >
            <Upload className="h-3.5 w-3.5" />
            Import JSON
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) {
                void handleImportFile(file);
              }
            }}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <label className="space-y-1">
            <span className="text-xs text-zinc-500">Save current style as preset</span>
            <input
              value={saveName}
              disabled={isBusy}
              onChange={(event) => setSaveName(event.target.value)}
              placeholder="Preset name"
              className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
            />
          </label>
          <button
            type="button"
            disabled={isBusy || !saveName.trim()}
            onClick={() => void handleSaveCurrent()}
            className="inline-flex h-8 items-center gap-1 self-end rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 text-xs font-medium text-emerald-100 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            Save preset
          </button>
        </div>

        {selectedPreset && !selectedPreset.is_builtin ? (
          <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
            <label className="block space-y-1">
              <span className="text-xs text-zinc-500">Rename custom preset</span>
              <div className="flex gap-2">
                <input
                  value={renameValue}
                  disabled={isBusy}
                  onChange={(event) => setRenameDraft(event.target.value)}
                  className="flex-1 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
                />
                <button
                  type="button"
                  disabled={isBusy || renameValue.trim() === selectedPreset.name}
                  onClick={() => void handleRename()}
                  className="rounded-lg border border-zinc-700 px-3 text-xs text-zinc-200 disabled:opacity-50"
                >
                  Rename
                </button>
              </div>
            </label>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={isBusy || !canUpdateSelected}
                onClick={() => void handleUpdateSelected()}
                className="inline-flex h-8 items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 text-xs font-medium text-emerald-100 disabled:opacity-50"
              >
                <Save className="h-3.5 w-3.5" />
                Update preset from current style
              </button>
              {confirmDeleteId === selectedPreset.id ? (
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void handleDelete()}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-3 text-xs font-medium text-red-100 disabled:opacity-50"
                >
                  Confirm delete
                </button>
              ) : (
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => setConfirmDeleteId(selectedPreset.id)}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-red-500/20 px-3 text-xs text-red-200 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete preset
                </button>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
