import type { ClipCandidate } from "@/lib/api/projects";

export type ClipCandidateSort = "score" | "shortest" | "longest" | "earliest";

export type ClipCandidateFilters = {
  minScore: number;
  minDuration: number;
  maxDuration: number;
  emotion: string;
  sort: ClipCandidateSort;
};

export const defaultClipCandidateFilters: ClipCandidateFilters = {
  minScore: 0,
  minDuration: 0,
  maxDuration: 9999,
  emotion: "all",
  sort: "score",
};

export function getClipEmotionOptions(candidates: ClipCandidate[]): string[] {
  return [
    "all",
    ...Array.from(new Set(candidates.map((candidate) => candidate.primary_emotion))).sort(),
  ];
}

export function filterClipCandidates(
  candidates: ClipCandidate[],
  filters: ClipCandidateFilters,
): ClipCandidate[] {
  return candidates.filter((candidate) => {
    if (candidate.score < filters.minScore) {
      return false;
    }
    if (candidate.duration < filters.minDuration) {
      return false;
    }
    if (candidate.duration > filters.maxDuration) {
      return false;
    }
    if (filters.emotion !== "all" && candidate.primary_emotion !== filters.emotion) {
      return false;
    }
    return true;
  });
}

export function sortClipCandidates(
  candidates: ClipCandidate[],
  sort: ClipCandidateSort,
): ClipCandidate[] {
  const sorted = [...candidates];

  switch (sort) {
    case "shortest":
      sorted.sort((left, right) => left.duration - right.duration || right.score - left.score);
      break;
    case "longest":
      sorted.sort((left, right) => right.duration - left.duration || right.score - left.score);
      break;
    case "earliest":
      sorted.sort((left, right) => left.start - right.start || right.score - left.score);
      break;
    case "score":
    default:
      sorted.sort(
        (left, right) =>
          right.score - left.score ||
          right.confidence - left.confidence ||
          left.start - right.start,
      );
      break;
  }

  return sorted;
}

export function filterAndSortClipCandidates(
  candidates: ClipCandidate[],
  filters: ClipCandidateFilters,
): ClipCandidate[] {
  return sortClipCandidates(filterClipCandidates(candidates, filters), filters.sort);
}
