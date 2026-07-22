import { describe, expect, it } from "vitest";
import type { ExportClipResponse } from "@/lib/api/projects";
import {
  filterAndSortExportedClips,
  filterExportedClips,
  getClipDisplayName,
  sortExportedClips,
} from "@/lib/exported-clips-library";

function makeClip(overrides: Partial<ExportClipResponse> = {}): ExportClipResponse {
  return {
    clip_id: "clip-1",
    project_id: "project-1",
    filename: "alpha-clip.mp4",
    relative_path: "project-1/clips/alpha-clip.mp4",
    media_url: "/api/projects/project-1/media/clips/clip-1",
    start_time: 0,
    end_time: 10,
    duration: 10,
    file_size_bytes: 1000,
    candidate_id: null,
    clip_name: "Alpha Clip",
    created_at: "2026-07-22T10:00:00Z",
    export_status: "completed",
    is_favorite: false,
    ...overrides,
  };
}

const clipAlpha = makeClip({
  clip_id: "clip-alpha",
  clip_name: "Alpha Clip",
  filename: "alpha-clip.mp4",
  created_at: "2026-07-22T10:00:00Z",
  duration: 10,
  is_favorite: false,
});

const clipBeta = makeClip({
  clip_id: "clip-beta",
  clip_name: "Beta Clip",
  filename: "beta-clip.mp4",
  created_at: "2026-07-22T12:00:00Z",
  duration: 20,
  is_favorite: true,
});

const clipGamma = makeClip({
  clip_id: "clip-gamma",
  clip_name: "Gamma Clip",
  filename: "gamma-clip.mp4",
  created_at: "2026-07-22T08:00:00Z",
  duration: 5,
  is_favorite: false,
});

const allClips = [clipAlpha, clipBeta, clipGamma];

describe("getClipDisplayName", () => {
  it("prefers clip_name over filename", () => {
    expect(getClipDisplayName(clipAlpha)).toBe("Alpha Clip");
  });

  it("falls back to filename when clip_name is missing", () => {
    expect(getClipDisplayName(makeClip({ clip_name: null }))).toBe("alpha-clip.mp4");
  });
});

describe("filterExportedClips", () => {
  it("searches by clip name case-insensitively", () => {
    expect(filterExportedClips(allClips, "alpha")).toEqual([clipAlpha]);
  });

  it("searches by filename case-insensitively", () => {
    expect(filterExportedClips(allClips, "BETA-CLIP")).toEqual([clipBeta]);
  });

  it("trims whitespace from the query", () => {
    expect(filterExportedClips(allClips, "  gamma  ")).toEqual([clipGamma]);
  });

  it("returns all clips when search is empty", () => {
    expect(filterExportedClips(allClips, "")).toEqual(allClips);
    expect(filterExportedClips(allClips, "   ")).toEqual(allClips);
  });

  it("does not mutate the original array", () => {
    const original = [...allClips];
    filterExportedClips(allClips, "alpha");
    expect(allClips).toEqual(original);
  });
});

describe("sortExportedClips", () => {
  it("sorts newest first by default", () => {
    expect(sortExportedClips(allClips, "newest").map((clip) => clip.clip_id)).toEqual([
      "clip-beta",
      "clip-alpha",
      "clip-gamma",
    ]);
  });

  it("sorts oldest first", () => {
    expect(sortExportedClips(allClips, "oldest").map((clip) => clip.clip_id)).toEqual([
      "clip-gamma",
      "clip-alpha",
      "clip-beta",
    ]);
  });

  it("sorts name A-Z", () => {
    expect(sortExportedClips(allClips, "name-asc").map((clip) => clip.clip_id)).toEqual([
      "clip-alpha",
      "clip-beta",
      "clip-gamma",
    ]);
  });

  it("sorts name Z-A", () => {
    expect(sortExportedClips(allClips, "name-desc").map((clip) => clip.clip_id)).toEqual([
      "clip-gamma",
      "clip-beta",
      "clip-alpha",
    ]);
  });

  it("sorts shortest duration", () => {
    expect(sortExportedClips(allClips, "shortest").map((clip) => clip.clip_id)).toEqual([
      "clip-gamma",
      "clip-alpha",
      "clip-beta",
    ]);
  });

  it("sorts longest duration", () => {
    expect(sortExportedClips(allClips, "longest").map((clip) => clip.clip_id)).toEqual([
      "clip-beta",
      "clip-alpha",
      "clip-gamma",
    ]);
  });

  it("sorts favorites first", () => {
    expect(sortExportedClips(allClips, "favorites-first").map((clip) => clip.clip_id)).toEqual([
      "clip-beta",
      "clip-alpha",
      "clip-gamma",
    ]);
  });

  it("does not mutate the original array", () => {
    const original = [...allClips];
    sortExportedClips(allClips, "name-asc");
    expect(allClips).toEqual(original);
  });
});

describe("filterAndSortExportedClips", () => {
  it("applies search and sort together", () => {
    const clips = [
      clipAlpha,
      makeClip({
        clip_id: "clip-alpha-fav",
        clip_name: "Alpha Favorite",
        filename: "alpha-favorite.mp4",
        created_at: "2026-07-22T11:00:00Z",
        is_favorite: true,
      }),
      clipBeta,
    ];

    const result = filterAndSortExportedClips(clips, "alpha", "favorites-first");
    expect(result.map((clip) => clip.clip_id)).toEqual(["clip-alpha-fav", "clip-alpha"]);
  });
});
