import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClipEditor } from "@/components/projects/ClipEditor";
import type { ExportClipResponse } from "@/lib/api/projects";

const exportedClip: ExportClipResponse = {
  clip_id: "clip-1",
  project_id: "project-1",
  filename: "sample-clip-title.mp4",
  relative_path: "project-1/clips/sample-clip-title.mp4",
  media_url: "/api/projects/project-1/media/clips/clip-1",
  start_time: 10,
  end_time: 25,
  duration: 15,
  file_size_bytes: 2048000,
  candidate_id: "candidate-123",
  clip_name: "Sample clip title",
  created_at: "2026-07-22T18:05:00Z",
  export_status: "completed",
  is_favorite: false,
};

afterEach(() => {
  cleanup();
});

describe("ClipEditor", () => {
  it("opens with current trim values and preview metadata", () => {
    render(
      <ClipEditor
        clip={exportedClip}
        sourceVideoUrl="http://localhost:8000/api/projects/project-1/media/video"
        frameRate={30}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: /edit clip sample clip title/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/start time/i)).toHaveValue("0:10.000");
    expect(screen.getByLabelText(/end time/i)).toHaveValue("0:25.000");
    expect(screen.getByText(/duration:/i)).toBeInTheDocument();
    expect(document.querySelector("video")?.getAttribute("src")).toBe(
      "http://localhost:8000/api/projects/project-1/media/video",
    );
  });

  it("updates duration when trim values change", () => {
    render(
      <ClipEditor
        clip={exportedClip}
        sourceVideoUrl="http://localhost:8000/api/projects/project-1/media/video"
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const startInput = screen.getByLabelText(/start time/i);
    fireEvent.change(startInput, { target: { value: "0:12.000" } });

    expect(screen.getByText("13s")).toBeInTheDocument();
  });

  it("saves trimmed clip successfully", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <ClipEditor
        clip={exportedClip}
        sourceVideoUrl="http://localhost:8000/api/projects/project-1/media/video"
        onSave={onSave}
        onClose={onClose}
      />,
    );

    fireEvent.change(screen.getByLabelText(/start time/i), {
      target: { value: "0:12.000" },
    });
    await user.click(screen.getByRole("button", { name: /save as new clip/i }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({
        startTime: expect.closeTo(12, 3),
        endTime: expect.closeTo(25, 3),
        clipName: "Sample clip title (trimmed)",
      });
    });
  });

  it("shows save failure from parent error prop", () => {
    render(
      <ClipEditor
        clip={exportedClip}
        sourceVideoUrl="http://localhost:8000/api/projects/project-1/media/video"
        error="Unable to save trimmed clip."
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Unable to save trimmed clip.")).toBeInTheDocument();
  });

  it("shows trimming progress while saving", () => {
    render(
      <ClipEditor
        clip={exportedClip}
        sourceVideoUrl="http://localhost:8000/api/projects/project-1/media/video"
        saving
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/saving trimmed clip/i)).toBeInTheDocument();
  });

  it("steps trim handles by frame", async () => {
    const user = userEvent.setup();

    render(
      <ClipEditor
        clip={exportedClip}
        sourceVideoUrl="http://localhost:8000/api/projects/project-1/media/video"
        frameRate={30}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /step start forward one frame/i }));

    expect(screen.getByLabelText(/start time/i)).toHaveValue("0:10.033");
  });
});
