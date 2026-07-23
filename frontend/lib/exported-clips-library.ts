import type { ExportClipResponse } from "@/lib/api/projects";

export type ExportedClipSort =
  | "newest"
  | "oldest"
  | "name-asc"
  | "name-desc"
  | "shortest"
  | "longest"
  | "favorites-first";

export const defaultExportedClipSort: ExportedClipSort = "newest";

export function getClipDisplayName(clip: ExportClipResponse): string {
  return clip.clip_name?.trim() || clip.filename;
}

export function isCaptionedExport(clip: ExportClipResponse): boolean {
  return clip.export_kind === "captioned";
}

export function canEditClipCaptions(clip: ExportClipResponse): boolean {
  return !isCaptionedExport(clip);
}

function compareCreatedAtDesc(left: ExportClipResponse, right: ExportClipResponse): number {
  return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
}

export function filterExportedClips(
  clips: ExportClipResponse[],
  searchQuery: string,
): ExportClipResponse[] {
  const normalizedQuery = searchQuery.trim().toLowerCase();
  if (!normalizedQuery) {
    return [...clips];
  }

  return clips.filter((clip) => {
    const displayName = getClipDisplayName(clip).toLowerCase();
    const filename = clip.filename.toLowerCase();
    return displayName.includes(normalizedQuery) || filename.includes(normalizedQuery);
  });
}

export function sortExportedClips(
  clips: ExportClipResponse[],
  sort: ExportedClipSort,
): ExportClipResponse[] {
  const sorted = [...clips];

  switch (sort) {
    case "oldest":
      sorted.sort(
        (left, right) =>
          new Date(left.created_at).getTime() - new Date(right.created_at).getTime() ||
          left.clip_id.localeCompare(right.clip_id),
      );
      break;
    case "name-asc":
      sorted.sort(
        (left, right) =>
          getClipDisplayName(left).localeCompare(getClipDisplayName(right), undefined, {
            sensitivity: "base",
          }) || left.clip_id.localeCompare(right.clip_id),
      );
      break;
    case "name-desc":
      sorted.sort(
        (left, right) =>
          getClipDisplayName(right).localeCompare(getClipDisplayName(left), undefined, {
            sensitivity: "base",
          }) || left.clip_id.localeCompare(right.clip_id),
      );
      break;
    case "shortest":
      sorted.sort(
        (left, right) =>
          left.duration - right.duration || compareCreatedAtDesc(left, right),
      );
      break;
    case "longest":
      sorted.sort(
        (left, right) =>
          right.duration - left.duration || compareCreatedAtDesc(left, right),
      );
      break;
    case "favorites-first":
      sorted.sort(
        (left, right) =>
          Number(right.is_favorite) - Number(left.is_favorite) ||
          compareCreatedAtDesc(left, right),
      );
      break;
    case "newest":
    default:
      sorted.sort(
        (left, right) =>
          compareCreatedAtDesc(left, right) || left.clip_id.localeCompare(right.clip_id),
      );
      break;
  }

  return sorted;
}

export function filterAndSortExportedClips(
  clips: ExportClipResponse[],
  searchQuery: string,
  sort: ExportedClipSort,
): ExportClipResponse[] {
  return sortExportedClips(filterExportedClips(clips, searchQuery), sort);
}
