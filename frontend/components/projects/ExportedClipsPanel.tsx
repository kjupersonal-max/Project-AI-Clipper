"use client";

import { useMemo, useState } from "react";
import type { ExportClipResponse } from "@/lib/api/projects";
import { resolveMediaUrl } from "@/lib/api/projects";
import { Badge } from "@/components/ui/Badge";
import {
  canEditClipCaptions,
  defaultExportedClipSort,
  filterAndSortExportedClips,
  getClipDisplayName,
  isCaptionedExport,
  type ExportedClipSort,
} from "@/lib/exported-clips-library";
import { getCaptionedExportLabel } from "@/lib/caption-render-mapping";
import { cn, formatDuration, formatFileSize } from "@/lib/utils";
import {
  CheckCircle2,
  Clock3,
  Download,
  Film,
  Loader2,
  Pencil,
  Scissors,
  Search,
  Star,
  Subtitles,
  Trash2,
  Video,
  X,
} from "lucide-react";

type ClipActionState = {
  renaming?: boolean;
  deleting?: boolean;
  favoriting?: boolean;
  error?: string | null;
};

type ExportedClipsPanelProps = {
  exportedClips: ExportClipResponse[];
  loading?: boolean;
  error?: string | null;
  onRename?: (clipId: string, clipName: string) => Promise<void>;
  onDelete?: (clipId: string) => Promise<void>;
  onFavorite?: (clipId: string, isFavorite: boolean) => Promise<void>;
  onEdit?: (clip: ExportClipResponse) => void;
  onCaptions?: (clip: ExportClipResponse) => void;
};

const SORT_OPTIONS: { value: ExportedClipSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "name-asc", label: "Name A–Z" },
  { value: "name-desc", label: "Name Z–A" },
  { value: "shortest", label: "Shortest duration" },
  { value: "longest", label: "Longest duration" },
  { value: "favorites-first", label: "Favorites first" },
];

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

function statusVariant(
  status: string,
): "default" | "success" | "warning" | "info" | "muted" {
  switch (status) {
    case "completed":
      return "success";
    case "processing":
      return "warning";
    case "failed":
      return "info";
    default:
      return "default";
  }
}

function getRenameDefaultValue(clip: ExportClipResponse): string {
  const trimmedName = clip.clip_name?.trim();
  if (trimmedName) {
    return trimmedName;
  }

  return clip.filename.replace(/\.mp4$/i, "");
}

type ExportedClipCardProps = {
  clip: ExportClipResponse;
  actionState?: ClipActionState;
  onRename?: (clipId: string, clipName: string) => Promise<void>;
  onDelete?: (clipId: string) => Promise<void>;
  onFavorite?: (clipId: string, isFavorite: boolean) => Promise<void>;
  onEdit?: (clip: ExportClipResponse) => void;
  onCaptions?: (clip: ExportClipResponse) => void;
};

function ExportedClipCard({
  clip,
  actionState,
  onRename,
  onDelete,
  onFavorite,
  onEdit,
  onCaptions,
}: ExportedClipCardProps) {
  const mediaUrl = resolveMediaUrl(clip.media_url);
  const displayName = getClipDisplayName(clip);
  const [isEditing, setIsEditing] = useState(false);
  const [renameValue, setRenameValue] = useState(getRenameDefaultValue(clip));
  const [renameValidationError, setRenameValidationError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const isRenaming = actionState?.renaming ?? false;
  const isDeleting = actionState?.deleting ?? false;
  const isFavoriting = actionState?.favoriting ?? false;
  const actionError = actionState?.error ?? null;
  const isBusy = isRenaming || isDeleting || isFavoriting;

  function startRename() {
    setRenameValue(getRenameDefaultValue(clip));
    setRenameValidationError(null);
    setIsEditing(true);
    setConfirmDelete(false);
  }

  function cancelRename() {
    setIsEditing(false);
    setRenameValue(getRenameDefaultValue(clip));
    setRenameValidationError(null);
  }

  async function submitRename() {
    const trimmed = renameValue.trim();
    if (!trimmed) {
      setRenameValidationError("Clip name cannot be empty.");
      return;
    }

    if (!onRename) {
      return;
    }

    setRenameValidationError(null);
    await onRename(clip.clip_id, trimmed);
    setIsEditing(false);
  }

  async function confirmDeleteClip() {
    if (!onDelete) {
      return;
    }

    await onDelete(clip.clip_id);
    setConfirmDelete(false);
  }

  async function toggleFavorite() {
    if (!onFavorite) {
      return;
    }

    await onFavorite(clip.clip_id, !clip.is_favorite);
  }

  return (
    <div className="overflow-hidden rounded-lg border border-emerald-500/30 bg-zinc-950/50 ring-1 ring-emerald-500/10">
      <div className="space-y-4 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="success">Exported clip</Badge>
          <Badge variant={statusVariant(clip.export_status)}>{clip.export_status}</Badge>
          {clip.is_favorite ? <Badge variant="warning">Favorite</Badge> : null}
        </div>

        <div className="flex items-start justify-between gap-3">
          {isEditing ? (
            <div className="min-w-0 flex-1 space-y-2">
              <label className="block text-xs font-medium text-zinc-400" htmlFor={`rename-${clip.clip_id}`}>
                Rename clip
              </label>
              <input
                id={`rename-${clip.clip_id}`}
                type="text"
                value={renameValue}
                onChange={(event) => {
                  setRenameValue(event.target.value);
                  if (renameValidationError) {
                    setRenameValidationError(null);
                  }
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void submitRename();
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    cancelRename();
                  }
                }}
                disabled={isRenaming}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500/30 focus:border-emerald-500/50 focus:ring-2"
                autoFocus
              />
              {renameValidationError ? (
                <p className="text-xs text-red-300">{renameValidationError}</p>
              ) : null}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void submitRename()}
                  disabled={isRenaming}
                  className={cn(
                    "inline-flex h-8 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 text-xs font-medium text-emerald-100 transition-colors hover:bg-emerald-500/20",
                    isRenaming && "cursor-not-allowed opacity-60",
                  )}
                >
                  {isRenaming ? (
                    <>
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    "Save"
                  )}
                </button>
                <button
                  type="button"
                  onClick={cancelRename}
                  disabled={isRenaming}
                  className="inline-flex h-8 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-zinc-100">{displayName}</p>
                {isCaptionedExport(clip) ? (
                  <Badge className="border-violet-500/30 bg-violet-500/10 text-violet-100">
                    {getCaptionedExportLabel(clip) ?? "Captioned"}
                  </Badge>
                ) : null}
              </div>
              <p className="mt-1 font-mono text-xs text-zinc-500">{clip.filename}</p>
            </div>
          )}

          {onFavorite ? (
            <button
              type="button"
              onClick={() => void toggleFavorite()}
              disabled={isBusy}
              aria-label={clip.is_favorite ? "Remove from favorites" : "Add to favorites"}
              aria-pressed={clip.is_favorite}
              className={cn(
                "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-colors",
                clip.is_favorite
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
                  : "border-zinc-800 bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
                isBusy && "cursor-not-allowed opacity-60",
              )}
            >
              {isFavoriting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Star className={cn("h-4 w-4", clip.is_favorite && "fill-current")} />
              )}
            </button>
          ) : null}
        </div>

        <dl className="grid gap-2 text-xs text-zinc-500 sm:grid-cols-2">
          <div>
            <dt className="font-medium text-zinc-400">Duration</dt>
            <dd className="mt-0.5 text-zinc-300">{formatDuration(clip.duration)}</dd>
          </div>
          <div>
            <dt className="font-medium text-zinc-400">File size</dt>
            <dd className="mt-0.5 text-zinc-300">{formatFileSize(clip.file_size_bytes)}</dd>
          </div>
          <div>
            <dt className="font-medium text-zinc-400">Created</dt>
            <dd className="mt-0.5 text-zinc-300">{new Date(clip.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="font-medium text-zinc-400">Source range</dt>
            <dd className="mt-0.5 inline-flex items-center gap-1 font-mono text-emerald-300">
              <Clock3 className="h-3 w-3" />
              {formatTimestamp(clip.start_time)} → {formatTimestamp(clip.end_time)}
            </dd>
          </div>
          {clip.candidate_id ? (
            <div className="sm:col-span-2">
              <dt className="font-medium text-zinc-400">Candidate source</dt>
              <dd className="mt-0.5 font-mono text-zinc-300">{clip.candidate_id}</dd>
            </div>
          ) : null}
        </dl>

        <div className="overflow-hidden rounded-lg border border-zinc-800 bg-black">
          <video
            src={mediaUrl}
            controls
            preload="metadata"
            className="aspect-video w-full bg-black"
          >
            Your browser does not support HTML5 video playback.
          </video>
        </div>

        {actionError ? (
          <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-300">
            {actionError}
          </div>
        ) : null}

        {confirmDelete ? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-3">
            <p className="text-sm text-red-100">
              Delete &quot;{displayName}&quot;? This removes the exported MP4 and cannot be undone.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void confirmDeleteClip()}
                disabled={isDeleting}
                className={cn(
                  "inline-flex h-8 items-center justify-center rounded-lg border border-red-500/40 bg-red-500/10 px-3 text-xs font-medium text-red-100 transition-colors hover:bg-red-500/20",
                  isDeleting && "cursor-not-allowed opacity-60",
                )}
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  "Delete clip"
                )}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                disabled={isDeleting}
                className="inline-flex h-8 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-800"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
        <p className="text-xs text-emerald-100/80">
          Rendered MP4 ready for download or preview.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {onEdit ? (
            <button
              type="button"
              onClick={() => onEdit(clip)}
              disabled={isBusy || isEditing}
              className={cn(
                "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 text-xs font-medium text-emerald-100 transition-colors hover:bg-emerald-500/10",
                (isBusy || isEditing) && "cursor-not-allowed opacity-60",
              )}
            >
              <Scissors className="h-3.5 w-3.5" />
              Edit
            </button>
          ) : null}
          {onCaptions ? (
            <button
              type="button"
              onClick={() => onCaptions(clip)}
              disabled={isBusy || isEditing || !canEditClipCaptions(clip)}
              title={
                canEditClipCaptions(clip)
                  ? "Edit captions"
                  : "Captioned exports cannot be re-captioned. Edit captions on the source clip."
              }
              className={cn(
                "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 text-xs font-medium text-sky-100 transition-colors hover:bg-sky-500/10",
                (isBusy || isEditing || !canEditClipCaptions(clip)) && "cursor-not-allowed opacity-60",
              )}
            >
              <Subtitles className="h-3.5 w-3.5" />
              Captions
            </button>
          ) : null}
          {onRename ? (
            <button
              type="button"
              onClick={startRename}
              disabled={isBusy || isEditing}
              className={cn(
                "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-800",
                (isBusy || isEditing) && "cursor-not-allowed opacity-60",
              )}
            >
              <Pencil className="h-3.5 w-3.5" />
              Rename
            </button>
          ) : null}
          {onDelete ? (
            <button
              type="button"
              onClick={() => {
                setConfirmDelete(true);
                setIsEditing(false);
              }}
              disabled={isBusy || confirmDelete}
              className={cn(
                "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/5 px-3 text-xs font-medium text-red-200 transition-colors hover:bg-red-500/10",
                (isBusy || confirmDelete) && "cursor-not-allowed opacity-60",
              )}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </button>
          ) : null}
          <a
            href={mediaUrl}
            download={clip.filename}
            className={cn(
              "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-800",
            )}
          >
            <Download className="h-3.5 w-3.5" />
            Download
          </a>
        </div>
      </div>
    </div>
  );
}

export function ExportedClipsState({
  loading,
  error,
}: {
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-zinc-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading exported clips...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-300">
        {error}
      </div>
    );
  }

  return null;
}

export function ExportedClipsPanel({
  exportedClips,
  loading = false,
  error = null,
  onRename,
  onDelete,
  onFavorite,
  onEdit,
  onCaptions,
}: ExportedClipsPanelProps) {
  const [clipActions, setClipActions] = useState<Record<string, ClipActionState>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [sort, setSort] = useState<ExportedClipSort>(defaultExportedClipSort);

  const visibleClips = useMemo(
    () => filterAndSortExportedClips(exportedClips, searchQuery, sort),
    [exportedClips, searchQuery, sort],
  );

  async function handleRename(clipId: string, clipName: string) {
    if (!onRename) {
      return;
    }

    setClipActions((current) => ({
      ...current,
      [clipId]: { ...current[clipId], renaming: true, error: null },
    }));

    try {
      await onRename(clipId, clipName);
      setClipActions((current) => ({
        ...current,
        [clipId]: { ...current[clipId], renaming: false, error: null },
      }));
    } catch (renameError) {
      const message =
        renameError &&
        typeof renameError === "object" &&
        "message" in renameError
          ? String((renameError as { message: string }).message)
          : "Unable to rename clip.";

      setClipActions((current) => ({
        ...current,
        [clipId]: { ...current[clipId], renaming: false, error: message },
      }));
    }
  }

  async function handleDelete(clipId: string) {
    if (!onDelete) {
      return;
    }

    setClipActions((current) => ({
      ...current,
      [clipId]: { ...current[clipId], deleting: true, error: null },
    }));

    try {
      await onDelete(clipId);
      setClipActions((current) => {
        const next = { ...current };
        delete next[clipId];
        return next;
      });
    } catch (deleteError) {
      const message =
        deleteError &&
        typeof deleteError === "object" &&
        "message" in deleteError
          ? String((deleteError as { message: string }).message)
          : "Unable to delete clip.";

      setClipActions((current) => ({
        ...current,
        [clipId]: { ...current[clipId], deleting: false, error: message },
      }));
    }
  }

  async function handleFavorite(clipId: string, isFavorite: boolean) {
    if (!onFavorite) {
      return;
    }

    setClipActions((current) => ({
      ...current,
      [clipId]: { ...current[clipId], favoriting: true, error: null },
    }));

    try {
      await onFavorite(clipId, isFavorite);
      setClipActions((current) => ({
        ...current,
        [clipId]: { ...current[clipId], favoriting: false, error: null },
      }));
    } catch (favoriteError) {
      const message =
        favoriteError &&
        typeof favoriteError === "object" &&
        "message" in favoriteError
          ? String((favoriteError as { message: string }).message)
          : "Unable to update favorite.";

      setClipActions((current) => ({
        ...current,
        [clipId]: { ...current[clipId], favoriting: false, error: message },
      }));
    }
  }

  if (loading || error) {
    return <ExportedClipsState loading={loading} error={error} />;
  }

  if (exportedClips.length === 0) {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-6">
        <Video className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
        <div>
          <p className="text-sm text-zinc-500">
            No exported clips yet. Use Export on a timeline clip candidate to render an MP4.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
        <Film className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
        <div>
          <p className="text-sm font-medium text-emerald-100">Rendered clip files</p>
          <p className="mt-1 text-sm text-emerald-100/80">
            Saved MP4 exports for this project. Preview inline, download, favorite, or search your clip library.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search by clip name or filename..."
            aria-label="Search exported clips"
            className="w-full rounded-lg border border-zinc-800 bg-zinc-950/60 py-2 pl-9 pr-9 text-sm text-zinc-100 outline-none ring-emerald-500/30 placeholder:text-zinc-500 focus:border-emerald-500/40 focus:ring-2"
          />
          {searchQuery.trim() ? (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>

        <label className="flex shrink-0 items-center gap-2 text-xs text-zinc-400">
          <span className="whitespace-nowrap">Sort by</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as ExportedClipSort)}
            aria-label="Sort exported clips"
            className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500/30 focus:border-emerald-500/40 focus:ring-2"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {visibleClips.length === 0 ? (
        <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 px-4 py-6">
          <Search className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
          <div>
            <p className="text-sm font-medium text-zinc-300">No matching clips</p>
            <p className="mt-1 text-sm text-zinc-500">
              No exported clips match &quot;{searchQuery.trim()}&quot;. Try a different search term or clear the filter.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {visibleClips.map((clip) => (
            <ExportedClipCard
              key={clip.clip_id}
              clip={clip}
              actionState={clipActions[clip.clip_id]}
              onRename={onRename ? handleRename : undefined}
              onDelete={onDelete ? handleDelete : undefined}
              onFavorite={onFavorite ? handleFavorite : undefined}
              onEdit={onEdit}
              onCaptions={onCaptions}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function ExportedClipsSummary({ count }: { count: number }) {
  if (count === 0) {
    return null;
  }

  return (
    <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
      <CheckCircle2 className="h-3.5 w-3.5" />
      {count} exported
    </span>
  );
}
