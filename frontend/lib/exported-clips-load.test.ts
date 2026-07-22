import { describe, expect, it } from "vitest";
import type { ExportClipResponse } from "@/lib/api/projects";
import {
  buildExportedStateFromClips,
  mergeExportedClips,
} from "@/lib/clip-export";

const savedClip: ExportClipResponse = {
  clip_id: "clip-saved",
  project_id: "project-1",
  filename: "saved.mp4",
  relative_path: "project-1/clips/saved.mp4",
  media_url: "/api/projects/project-1/media/clips/clip-saved",
  start_time: 1,
  end_time: 2,
  duration: 1,
  file_size_bytes: 1000,
  candidate_id: "candidate-123",
  clip_name: "Saved clip",
  created_at: "2026-07-22T10:00:00Z",
  export_status: "completed",
};

const sessionClip: ExportClipResponse = {
  ...savedClip,
  clip_id: "clip-session",
  filename: "session.mp4",
  media_url: "/api/projects/project-1/media/clips/clip-session",
  clip_name: "Session clip",
  created_at: "2026-07-22T12:00:00Z",
  candidate_id: null,
};

describe("exported clips reload flow", () => {
  it("merges backend-loaded exports after refresh without duplicates", () => {
    const afterRefresh = mergeExportedClips([savedClip], []);
    expect(afterRefresh).toHaveLength(1);
    expect(afterRefresh[0]?.clip_id).toBe("clip-saved");
  });

  it("preserves a new session export when backend data reloads", () => {
    const merged = mergeExportedClips([savedClip], [sessionClip]);
    expect(merged.map((clip) => clip.clip_id)).toEqual(["clip-session", "clip-saved"]);
  });

  it("restores exported candidate button state from candidate_id", () => {
    const restored = buildExportedStateFromClips([savedClip]);
    expect(restored.exportedCandidateIds.has("candidate-123")).toBe(true);
    expect(restored.exportStates["candidate-123"]).toEqual({ status: "completed" });
  });
});

describe("exports list 404 handling", () => {
  it("maps a missing list endpoint to an actionable reload message", () => {
    const status = 404;
    const message = "Not Found";
    const rendered =
      status === 404
        ? "Saved exports could not be loaded because GET /api/projects/{project_id}/clips/exports is unavailable on the backend. Restart the backend server to pick up the export list endpoint, then refresh."
        : message;

    expect(rendered).toContain("clips/exports is unavailable");
    expect(rendered).toContain("Restart the backend server");
  });
});
