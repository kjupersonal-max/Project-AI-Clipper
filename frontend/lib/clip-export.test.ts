import { describe, expect, it } from "vitest";
import type { ClipCandidate, SegmentAnalysis } from "@/lib/api/projects";
import {
  buildExportClipRequest,
  buildExportClipRequestFromSegment,
  buildExportKeyFromSegment,
  buildExportedStateFromClips,
  clearCandidateExportedState,
  deriveClipName,
  deriveClipNameFromSegment,
  isCandidateExported,
  isCandidateExporting,
  mergeExportedClips,
  mergeLoadedExports,
  removeExportedClip,
  updateExportedClip,
} from "@/lib/clip-export";
import type { ExportClipResponse } from "@/lib/api/projects";

const sampleCandidate: ClipCandidate = {
  clip_id: "candidate-123",
  start: 12.5,
  end: 45.0,
  duration: 32.5,
  segment_ids: [1, 2],
  transcript_text: "This is a sample transcript for the clip candidate.",
  score: 88.5,
  confidence: 0.92,
  primary_emotion: "excitement",
  hook_score: 90,
  payoff_score: 85,
  standalone_score: 80,
  context_dependency_score: 20,
  title_suggestion: "Big reveal moment",
  reason: "Strong hook and payoff.",
  status: "proposed",
};

const sampleSegment: SegmentAnalysis = {
  segment_id: 7,
  start: 10,
  end: 25,
  text: "This segment looks like a strong short-form clip.",
  emotion: "excitement",
  excitement_score: 90,
  humor_score: 20,
  suspense_score: 15,
  educational_score: 30,
  standalone_score: 85,
  context_dependency_score: 10,
  clip_candidate: true,
  reason: "High excitement and standalone score.",
};

describe("buildExportClipRequestFromSegment", () => {
  it("sends segment timestamps and derived clip name without candidate_id", () => {
    expect(buildExportClipRequestFromSegment(sampleSegment)).toEqual({
      start_time: 10,
      end_time: 25,
      clip_name: "This segment looks like a strong short-form clip.",
      candidate_id: null,
    });
  });

  it("uses a stable export key for timeline segments", () => {
    expect(buildExportKeyFromSegment(sampleSegment)).toBe("segment-7");
  });
});

describe("deriveClipNameFromSegment", () => {
  it("derives clip name from segment text", () => {
    expect(deriveClipNameFromSegment(sampleSegment)).toBe(
      "This segment looks like a strong short-form clip.",
    );
  });
});

describe("buildExportClipRequest", () => {
  it("sends candidate timestamps, name, and candidate_id", () => {
    expect(buildExportClipRequest(sampleCandidate)).toEqual({
      start_time: 12.5,
      end_time: 45.0,
      clip_name: "Big reveal moment",
      candidate_id: "candidate-123",
    });
  });

  it("derives clip name from transcript when title is missing", () => {
    const candidate = {
      ...sampleCandidate,
      title_suggestion: "",
    };

    expect(buildExportClipRequest(candidate).clip_name).toBe(
      "This is a sample transcript for the clip candidate.",
    );
  });
});

describe("deriveClipName", () => {
  it("prefers title suggestion", () => {
    expect(deriveClipName(sampleCandidate)).toBe("Big reveal moment");
  });

  it("falls back to timestamp-based name", () => {
    const candidate = {
      ...sampleCandidate,
      title_suggestion: "",
      transcript_text: "",
    };

    expect(deriveClipName(candidate)).toBe("clip-0:12");
  });
});

describe("export state helpers", () => {
  it("detects exported candidates from session set", () => {
    expect(
      isCandidateExported("candidate-123", new Set(["candidate-123"]), {}),
    ).toBe(true);
  });

  it("detects completed export state", () => {
    expect(
      isCandidateExported("candidate-123", new Set(), {
        "candidate-123": { status: "completed" },
      }),
    ).toBe(true);
  });

  it("detects exporting state", () => {
    expect(
      isCandidateExporting("candidate-123", {
        "candidate-123": { status: "exporting" },
      }),
    ).toBe(true);
  });
});

const savedClip: ExportClipResponse = {
  clip_id: "clip-1",
  project_id: "project-1",
  filename: "saved.mp4",
  relative_path: "project-1/clips/saved.mp4",
  media_url: "/api/projects/project-1/media/clips/clip-1",
  start_time: 1,
  end_time: 2,
  duration: 1,
  file_size_bytes: 1000,
  candidate_id: "candidate-123",
  clip_name: "Saved clip",
  created_at: "2026-07-22T10:00:00Z",
  export_status: "completed",
  is_favorite: false,
};

const sessionClip: ExportClipResponse = {
  ...savedClip,
  clip_id: "clip-2",
  filename: "session.mp4",
  media_url: "/api/projects/project-1/media/clips/clip-2",
  clip_name: "Session clip",
  created_at: "2026-07-22T12:00:00Z",
  candidate_id: null,
};

describe("mergeExportedClips", () => {
  it("merges saved and session exports without duplicates", () => {
    const merged = mergeExportedClips([savedClip], [savedClip, sessionClip]);

    expect(merged).toHaveLength(2);
    expect(merged.map((clip) => clip.clip_id)).toEqual(["clip-2", "clip-1"]);
  });
});

describe("buildExportedStateFromClips", () => {
  it("restores exported candidate state when candidate_id exists", () => {
    const restored = buildExportedStateFromClips([savedClip]);

    expect(restored.exportedCandidateIds).toEqual(new Set(["candidate-123"]));
    expect(restored.exportStates).toEqual({
      "candidate-123": { status: "completed" },
    });
  });

  it("ignores exports without candidate_id", () => {
    const restored = buildExportedStateFromClips([sessionClip]);

    expect(restored.exportedCandidateIds.size).toBe(0);
    expect(restored.exportStates).toEqual({});
  });
});

describe("mergeLoadedExports", () => {
  it("preserves session-only exports not yet returned by the backend", () => {
    const merged = mergeLoadedExports([savedClip], [sessionClip]);
    expect(merged.map((clip) => clip.clip_id)).toEqual(["clip-2", "clip-1"]);
  });

  it("does not reintroduce a clip removed from client state after backend delete", () => {
    const merged = mergeLoadedExports([sessionClip], [sessionClip]);
    expect(merged.map((clip) => clip.clip_id)).toEqual(["clip-2"]);
  });
});

describe("updateExportedClip", () => {
  it("replaces an existing clip by clip_id", () => {
    const updated = {
      ...savedClip,
      clip_name: "Renamed clip",
    };

    expect(updateExportedClip([savedClip, sessionClip], updated)).toEqual([
      sessionClip,
      updated,
    ]);
  });
});

describe("removeExportedClip", () => {
  it("removes a clip from the list", () => {
    expect(removeExportedClip([savedClip, sessionClip], savedClip.clip_id)).toEqual([
      sessionClip,
    ]);
  });
});

describe("clearCandidateExportedState", () => {
  it("clears candidate exported state so it can be exported again", () => {
    const cleared = clearCandidateExportedState(
      "candidate-123",
      new Set(["candidate-123", "candidate-456"]),
      {
        "candidate-123": { status: "completed" },
        "candidate-456": { status: "completed" },
      },
    );

    expect(cleared.exportedCandidateIds).toEqual(new Set(["candidate-456"]));
    expect(cleared.exportStates).toEqual({
      "candidate-456": { status: "completed" },
    });
  });
});
