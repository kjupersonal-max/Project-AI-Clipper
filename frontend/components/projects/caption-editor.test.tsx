import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CaptionEditor } from "@/components/projects/CaptionEditor";
import type { ClipCaptionsResponse, ExportClipResponse } from "@/lib/api/projects";

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

const captions: ClipCaptionsResponse = {
  project_id: "project-1",
  clip_id: "clip-1",
  source_start_time: 10,
  source_end_time: 25,
  duration: 15,
  candidate_id: "candidate-123",
  segments: [
    {
      id: "cap-1",
      text: "First caption",
      start: 0,
      end: 2,
      words: [],
      sequence: 0,
      created_at: "2026-07-22T18:10:00Z",
      updated_at: "2026-07-22T18:10:00Z",
    },
    {
      id: "cap-2",
      text: "Second caption",
      start: 2,
      end: 5,
      words: [],
      sequence: 1,
      created_at: "2026-07-22T18:10:00Z",
      updated_at: "2026-07-22T18:10:00Z",
    },
  ],
  created_at: "2026-07-22T18:10:00Z",
  updated_at: "2026-07-22T18:10:00Z",
};

afterEach(() => {
  cleanup();
});

describe("CaptionEditor", () => {
  it("opens with loading and empty states", () => {
    const { rerender } = render(
      <CaptionEditor
        clip={exportedClip}
        captions={null}
        loading
        onGenerate={vi.fn()}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/loading captions/i)).toBeInTheDocument();

    rerender(
      <CaptionEditor
        clip={exportedClip}
        captions={null}
        onGenerate={vi.fn()}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/no captions yet/i)).toBeInTheDocument();
  });

  it("loads saved captions and highlights active caption during playback", () => {
    render(
      <CaptionEditor
        clip={exportedClip}
        captions={captions}
        onGenerate={vi.fn()}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByDisplayValue("First caption")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Second caption")).toBeInTheDocument();

    const video = document.querySelector("video");
    expect(video).toBeTruthy();
    fireEvent.timeUpdate(video!, { target: { currentTime: 1 } });
    expect(screen.getAllByText("First caption").length).toBeGreaterThan(0);
  });

  it("generates captions from the action button", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn().mockResolvedValue(undefined);

    render(
      <CaptionEditor
        clip={exportedClip}
        captions={null}
        onGenerate={onGenerate}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getAllByRole("button", { name: /generate captions/i })[0]);
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it("seeks video when clicking a caption row", async () => {
    const user = userEvent.setup();

    render(
      <CaptionEditor
        clip={exportedClip}
        captions={captions}
        onGenerate={vi.fn()}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const video = document.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      writable: true,
      value: 0,
    });

    await user.click(screen.getByText(/caption 2/i));
    expect(video.currentTime).toBe(2);
  });

  it("edits caption text and timing then saves successfully", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <CaptionEditor
        clip={exportedClip}
        captions={captions}
        onGenerate={vi.fn()}
        onSave={onSave}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByDisplayValue("First caption"), {
      target: { value: "Updated caption" },
    });
    fireEvent.change(screen.getByLabelText(/caption 1 start time/i), {
      target: { value: "0:00.500" },
    });

    await user.click(screen.getByRole("button", { name: /save captions/i }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            id: "cap-1",
            text: "Updated caption",
            start: 0.5,
          }),
        ]),
      );
    });
  });

  it("shows save failure from parent error state", () => {
    render(
      <CaptionEditor
        clip={exportedClip}
        captions={captions}
        error="Unable to save captions."
        onGenerate={vi.fn()}
        onSave={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/unable to save captions/i)).toBeInTheDocument();
  });

  it("requires confirmation before resetting captions", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn().mockResolvedValue(undefined);

    render(
      <CaptionEditor
        clip={exportedClip}
        captions={captions}
        onGenerate={vi.fn()}
        onSave={vi.fn()}
        onReset={onReset}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /reset captions/i }));
    expect(onReset).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /confirm reset/i }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
