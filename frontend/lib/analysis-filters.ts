import type { SegmentAnalysis } from "@/lib/api/projects";

export type AnalysisFilters = {
  clipCandidatesOnly: boolean;
  minExcitement: number;
  emotion: string;
};

export const defaultAnalysisFilters: AnalysisFilters = {
  clipCandidatesOnly: false,
  minExcitement: 0,
  emotion: "all",
};

export function getEmotionOptions(segments: SegmentAnalysis[]): string[] {
  return ["all", ...Array.from(new Set(segments.map((segment) => segment.emotion))).sort()];
}

export function filterSegmentAnalysis(
  segments: SegmentAnalysis[],
  filters: AnalysisFilters,
): SegmentAnalysis[] {
  return segments.filter((segment) => {
    if (filters.clipCandidatesOnly && !segment.clip_candidate) {
      return false;
    }
    if (segment.excitement_score < filters.minExcitement) {
      return false;
    }
    if (filters.emotion !== "all" && segment.emotion !== filters.emotion) {
      return false;
    }
    return true;
  });
}

export function segmentMatchesFilters(
  segment: SegmentAnalysis,
  filters: AnalysisFilters,
): boolean {
  return filterSegmentAnalysis([segment], filters).length === 1;
}
