import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  deleteProjectClip,
  deleteProjectClipCaptions,
  exportProjectClip,
  favoriteProjectClip,
  fetchProjectClipCaptions,
  fetchProjectClipExports,
  generateProjectClipCaptions,
  renameProjectClip,
  resolveMediaUrl,
  trimProjectClip,
  updateProjectClipCaptions,
} from "@/lib/api/projects";

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
      is_favorite: false,
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

describe("fetchProjectClipExports", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads saved exports for a project", async () => {
    const mockResponse = {
      project_id: "project-1",
      exports: [
        {
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
          is_favorite: true,
        },
      ],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchProjectClipExports("project-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/exports",
      { cache: "no-store" },
    );
    expect(result).toEqual(mockResponse);
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

describe("renameProjectClip", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("patches the clip name to the backend", async () => {
    const mockResponse = {
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
      clip_name: "Renamed clip",
      created_at: "2026-07-22T10:00:00Z",
      export_status: "completed",
      is_favorite: false,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await renameProjectClip("project-1", "clip-1", {
      clip_name: "Renamed clip",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip_name: "Renamed clip" }),
      }),
    );
    expect(result).toEqual(mockResponse);
  });

  it("throws backend error messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: "clip_name must not be empty." }),
      statusText: "Unprocessable Entity",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      renameProjectClip("project-1", "clip-1", { clip_name: "   " }),
    ).rejects.toEqual({
      message: "clip_name must not be empty.",
      status: 422,
    });
  });
});

describe("deleteProjectClip", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("deletes a clip from the backend", async () => {
    const mockResponse = {
      project_id: "project-1",
      clip_id: "clip-1",
      message: "Exported clip deleted successfully.",
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await deleteProjectClip("project-1", "clip-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1",
      expect.objectContaining({
        method: "DELETE",
      }),
    );
    expect(result).toEqual(mockResponse);
  });

  it("throws backend error messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Exported clip 'clip-1' was not found." }),
      statusText: "Not Found",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteProjectClip("project-1", "clip-1")).rejects.toEqual({
      message: "Exported clip 'clip-1' was not found.",
      status: 404,
    });
  });
});

describe("trimProjectClip", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts trim values to the backend", async () => {
    const mockResponse = {
      clip_id: "clip-trimmed",
      project_id: "project-1",
      filename: "trimmed.mp4",
      relative_path: "project-1/clips/trimmed.mp4",
      media_url: "/api/projects/project-1/media/clips/clip-trimmed",
      start_time: 12,
      end_time: 20,
      duration: 8,
      file_size_bytes: 900,
      candidate_id: "candidate-123",
      clip_name: "Sample clip (trimmed)",
      created_at: "2026-07-22T18:10:00Z",
      export_status: "completed",
      is_favorite: false,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await trimProjectClip("project-1", "clip-1", {
      start_time: 12,
      end_time: 20,
      clip_name: "Sample clip (trimmed)",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1/trim",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_time: 12,
          end_time: 20,
          clip_name: "Sample clip (trimmed)",
        }),
      }),
    );
    expect(result).toEqual(mockResponse);
  });
});

describe("favoriteProjectClip", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("patches favorite state to the backend", async () => {
    const mockResponse = {
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
      is_favorite: true,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await favoriteProjectClip("project-1", "clip-1", {
      is_favorite: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1/favorite",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_favorite: true }),
      }),
    );
    expect(result).toEqual(mockResponse);
  });

  it("throws backend error messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Exported clip 'clip-1' was not found." }),
      statusText: "Not Found",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      favoriteProjectClip("project-1", "clip-1", { is_favorite: true }),
    ).rejects.toEqual({
      message: "Exported clip 'clip-1' was not found.",
      status: 404,
    });
  });
});

describe("clip caption API helpers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts caption generation requests", async () => {
    const mockResponse = {
      project_id: "project-1",
      clip_id: "clip-1",
      source_start_time: 1,
      source_end_time: 5,
      duration: 4,
      candidate_id: null,
      segments: [],
      created_at: "2026-07-22T18:00:00Z",
      updated_at: "2026-07-22T18:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await generateProjectClipCaptions("project-1", "clip-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1/captions/generate",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual(mockResponse);
  });

  it("loads saved captions", async () => {
    const mockResponse = {
      project_id: "project-1",
      clip_id: "clip-1",
      source_start_time: 1,
      source_end_time: 5,
      duration: 4,
      candidate_id: null,
      segments: [
        {
          id: "cap-1",
          text: "Hello",
          start: 0,
          end: 1,
          words: [],
          sequence: 0,
          created_at: "t",
          updated_at: "t",
        },
      ],
      created_at: "2026-07-22T18:00:00Z",
      updated_at: "2026-07-22T18:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchProjectClipCaptions("project-1", "clip-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1/captions",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(result.segments).toHaveLength(1);
  });

  it("updates captions with PUT payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ project_id: "project-1", clip_id: "clip-1", segments: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await updateProjectClipCaptions("project-1", "clip-1", {
      segments: [{ id: "cap-1", text: "Updated", start: 0, end: 1, sequence: 0 }],
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1/captions",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          segments: [{ id: "cap-1", text: "Updated", start: 0, end: 1, sequence: 0 }],
        }),
      }),
    );
  });

  it("deletes captions", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: "project-1",
        clip_id: "clip-1",
        message: "Captions deleted successfully.",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await deleteProjectClipCaptions("project-1", "clip-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/project-1/clips/clip-1/captions",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
