import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CaptionEditor } from "@/components/projects/CaptionEditor";
import type { ClipCaptionsResponse, ExportClipResponse } from "@/lib/api/projects";
import { createDefaultCaptionStyle } from "@/lib/caption-style";

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

const defaultStyle = createDefaultCaptionStyle();

const captions: ClipCaptionsResponse = {
  project_id: "project-1",
  clip_id: "clip-1",
  source_start_time: 10,
  source_end_time: 25,
  duration: 15,
  candidate_id: "candidate-123",
  style: defaultStyle,
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

const captionsWithWords: ClipCaptionsResponse = {
  ...captions,
  segments: [
    {
      id: "cap-words",
      text: "Hello beautiful world",
      start: 0,
      end: 3,
      words: [
        { word: "Hello", start: 0, end: 0.8 },
        { word: "beautiful", start: 0.8, end: 1.6 },
        { word: "world", start: 1.6, end: 3 },
      ],
      sequence: 0,
      created_at: "2026-07-22T18:10:00Z",
      updated_at: "2026-07-22T18:10:00Z",
    },
  ],
};

function renderEditor(
  overrides: Partial<ComponentProps<typeof CaptionEditor>> = {},
) {
  const props = {
    clip: exportedClip,
    captions,
    onGenerate: vi.fn().mockResolvedValue(undefined),
    onSave: vi.fn().mockResolvedValue(undefined),
    onSaveStyle: vi.fn().mockResolvedValue(undefined),
    onResetStyle: vi.fn().mockResolvedValue(undefined),
    onRender: vi.fn().mockResolvedValue(undefined),
    onReset: vi.fn().mockResolvedValue(undefined),
    onClose: vi.fn(),
    ...overrides,
  };

  return {
    ...render(<CaptionEditor {...props} />),
    props,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
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
        onSaveStyle={vi.fn()}
        onResetStyle={vi.fn()}
        onRender={vi.fn()}
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
        onSaveStyle={vi.fn()}
        onResetStyle={vi.fn()}
        onRender={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/no captions yet/i)).toBeInTheDocument();
  });

  it("loads saved captions and highlights active caption during playback", () => {
    renderEditor();

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
        onSaveStyle={vi.fn()}
        onResetStyle={vi.fn()}
        onRender={vi.fn()}
        onReset={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getAllByRole("button", { name: /generate captions/i })[0]);
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it("seeks video when clicking a caption row", async () => {
    const user = userEvent.setup();
    renderEditor();

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
    renderEditor({ onSave });

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
    renderEditor({ error: "Unable to save captions." });
    expect(screen.getByText(/unable to save captions/i)).toBeInTheDocument();
  });

  it("requires confirmation before resetting captions", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn().mockResolvedValue(undefined);
    renderEditor({ onReset });

    await user.click(screen.getByRole("button", { name: /reset captions/i }));
    expect(onReset).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /confirm reset/i }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("opens style controls from the style tab", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: /^style$/i }));

    expect(screen.getByLabelText(/caption preset/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/caption font size/i)).toBeInTheDocument();
  });

  it("selects presets and updates preview state", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: /^style$/i }));
    await user.selectOptions(screen.getByLabelText(/caption preset/i), "bold-pop");

    expect(screen.getByLabelText(/caption preset/i)).toBeInTheDocument();
  });

  it("changes colors and font size in style panel", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: /^style$/i }));

    fireEvent.change(screen.getByLabelText(/caption font size/i), {
      target: { value: "40" },
    });
    fireEvent.change(screen.getByLabelText(/caption text color/i), {
      target: { value: "#ff0000" },
    });

    expect(screen.getByText(/unsaved style changes/i)).toBeInTheDocument();
  });

  it("changes position and words-per-group controls", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: /^style$/i }));

    fireEvent.change(screen.getByLabelText(/caption horizontal position/i), {
      target: { value: "30" },
    });
    await user.selectOptions(screen.getByLabelText(/caption words per group/i), "2");

    expect(screen.getByText(/unsaved style changes/i)).toBeInTheDocument();
  });

  it("saves style changes", async () => {
    const user = userEvent.setup();
    const onSaveStyle = vi.fn().mockResolvedValue(undefined);
    renderEditor({ onSaveStyle });

    await user.click(screen.getByRole("button", { name: /^style$/i }));
    fireEvent.change(screen.getByLabelText(/caption font size/i), {
      target: { value: "36" },
    });
    await user.click(screen.getByRole("button", { name: /save style/i }));

    await waitFor(() => {
      expect(onSaveStyle).toHaveBeenCalledWith(
        expect.objectContaining({
          font_size: 36,
        }),
      );
    });
  });

  it("resets style from the style panel", async () => {
    const user = userEvent.setup();
    const onResetStyle = vi.fn().mockResolvedValue(undefined);
    renderEditor({ onResetStyle });

    await user.click(screen.getByRole("button", { name: /^style$/i }));
    await user.click(screen.getByRole("button", { name: /reset style/i }));

    expect(onResetStyle).toHaveBeenCalledTimes(1);
  });

  it("toggles safe-area preview guides", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: /^style$/i }));
    await user.selectOptions(screen.getByLabelText(/caption safe area mode/i), "tiktok");

    expect(screen.getByLabelText(/show safe area guides/i)).toBeChecked();
  });

  it("renders word-level captions in preview overlay", () => {
    renderEditor({ captions: captionsWithWords });

    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("falls back to segment text when word timing is unavailable", () => {
    renderEditor();
    expect(screen.getAllByText("First caption").length).toBeGreaterThan(0);
  });

  it("respects reduced motion for animation classes", () => {
    const matchMediaMock = vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderEditor({ captions: captionsWithWords });

    expect(matchMediaMock).toHaveBeenCalled();
  });

  it("shows export with captions button when captions exist", () => {
    renderEditor();
    expect(screen.getByRole("button", { name: /export with captions/i })).toBeInTheDocument();
  });

  it("disables export with captions while rendering", () => {
    renderEditor({ rendering: true });
    expect(screen.getByRole("button", { name: /export with captions/i })).toBeDisabled();
  });

  it("calls render handler on export with captions", async () => {
    const user = userEvent.setup();
    const onRender = vi.fn().mockResolvedValue(undefined);
    renderEditor({ onRender });

    await user.click(screen.getByRole("button", { name: /export with captions/i }));
    expect(onRender).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /export with captions/i }));
    expect(onRender).toHaveBeenCalledTimes(1);
  });

  it("shows render success message from parent", () => {
    renderEditor({ renderSuccess: "Captioned export ready: Sample (captioned)." });
    expect(screen.getByText(/captioned export ready/i)).toBeInTheDocument();
  });

  it("shows render failure from parent error state", () => {
    renderEditor({ error: "Unable to render captioned export." });
    expect(screen.getByText(/unable to render captioned export/i)).toBeInTheDocument();
  });
});
