import { describe, expect, it, vi, beforeEach } from "vitest";
import { exportProjectClip, resolveMediaUrl } from "@/lib/api/projects";

describe("exportProjectClip", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts the export payload to the backend", async () => {
    const mockResponse = {
      clip_id: "clip-1",
      project_id: "project-1",
      filename: "big-reveal.mp4",
      relative_path: "project-1/clips/big-reveal.mp4",
      media_url: "/api/projects/project-1/media/clips/clip-1",
      start_time: 12.5,
      end_time: 45,
      duration: 32.5,
      file_size_bytes: 1024,
      candidate_id: "candidate-123",
      clip_name: "Big reveal moment",
      created_at: "2026-07-22T18:00:00Z",
      export_status: "completed",
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await exportProjectClip("project-1", {
      start_time: 12.5,
      end_time: 45,
      clip_name: "Big reveal moment",
      candidate_id: "candidate-123",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/export",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_time: 12.5,
          end_time: 45,
          clip_name: "Big reveal moment",
          candidate_id: "candidate-123",
        }),
      }),
    );
    expect(result).toEqual(mockResponse);
  });

  it("throws backend error messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: "Clip duration exceeds maximum allowed length." }),
      statusText: "Unprocessable Entity",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      exportProjectClip("project-1", {
        start_time: 0,
        end_time: 999,
      }),
    ).rejects.toEqual({
      message: "Clip duration exceeds maximum allowed length.",
      status: 422,
    });
  });
});

describe("resolveMediaUrl", () => {
  it("prefixes relative media URLs with the API base URL", () => {
    expect(resolveMediaUrl("/api/projects/project-1/media/clips/clip-1")).toBe(
      "http://localhost:8000/api/projects/project-1/media/clips/clip-1",
    );
  });

  it("returns absolute URLs unchanged", () => {
    expect(resolveMediaUrl("https://cdn.example.com/clip.mp4")).toBe(
      "https://cdn.example.com/clip.mp4",
    );
  });
});
