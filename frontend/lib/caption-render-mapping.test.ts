import { describe, expect, it } from "vitest";
import {
  getCaptionedExportLabel,
  isCaptionedExport,
} from "@/lib/caption-render-mapping";
import type { ExportClipResponse } from "@/lib/api/projects";

const rawClip: ExportClipResponse = {
  clip_id: "clip-raw",
  project_id: "project-1",
  filename: "clip.mp4",
  relative_path: "project-1/clips/clip.mp4",
  media_url: "/api/projects/project-1/media/clips/clip-raw",
  start_time: 0,
  end_time: 5,
  duration: 5,
  file_size_bytes: 1000,
  candidate_id: null,
  clip_name: "Clip",
  created_at: "2026-07-22T18:00:00Z",
  export_status: "completed",
  is_favorite: false,
  export_kind: "raw",
};

const captionedClip: ExportClipResponse = {
  ...rawClip,
  clip_id: "clip-captioned",
  clip_name: "Clip (captioned)",
  export_kind: "captioned",
  source_clip_id: "clip-raw",
  caption_style_preset: "bold-pop",
};

describe("caption render mapping", () => {
  it("identifies captioned exports", () => {
    expect(isCaptionedExport(captionedClip)).toBe(true);
    expect(isCaptionedExport(rawClip)).toBe(false);
    expect(isCaptionedExport({})).toBe(false);
  });

  it("builds captioned export labels", () => {
    expect(getCaptionedExportLabel(captionedClip)).toBe("Captioned · bold pop");
    expect(getCaptionedExportLabel(rawClip)).toBeNull();
  });
});
