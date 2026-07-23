import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TranscriptionRecoveryPanel } from "@/components/projects/TranscriptionRecoveryPanel";
import type { ClipCaptionsResponse } from "@/lib/api/projects";
import { createDefaultCaptionStyle } from "@/lib/caption-style";

vi.mock("@/lib/api/projects", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/projects")>("@/lib/api/projects");
  return {
    ...actual,
    previewRetranscribeRange: vi.fn(),
    applyRetranscribeRange: vi.fn(),
    updateClipVocabularyHints: vi.fn(),
  };
});

const captions: ClipCaptionsResponse = {
  project_id: "project-1",
  clip_id: "clip-1",
  source_start_time: 0,
  source_end_time: 10,
  duration: 10,
  candidate_id: null,
  style: createDefaultCaptionStyle(),
  segments: [
    {
      id: "cap-1",
      text: "Hello world",
      start: 0,
      end: 2,
      words: [],
      sequence: 0,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  transcription_quality_rating: "review_recommended",
  transcription_warnings: ["Possible missing speech"],
};

describe("TranscriptionRecoveryPanel", () => {
  it("shows quality mode selector and warnings", () => {
    render(
      <TranscriptionRecoveryPanel
        projectId="project-1"
        clipId="clip-1"
        clipDuration={10}
        captions={captions}
        selectedSegmentId="cap-1"
        playbackTime={1}
        onCaptionsUpdated={vi.fn()}
        onSegmentsUpdated={vi.fn()}
        onError={vi.fn()}
      />,
    );

    expect(screen.getByText("Transcription quality")).toBeInTheDocument();
    expect(screen.getByText("Possible missing speech")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("shows high accuracy warning when selected", async () => {
    const user = userEvent.setup();
    render(
      <TranscriptionRecoveryPanel
        projectId="project-1"
        clipId="clip-1"
        clipDuration={10}
        captions={captions}
        selectedSegmentId="cap-1"
        playbackTime={1}
        onCaptionsUpdated={vi.fn()}
        onSegmentsUpdated={vi.fn()}
        onError={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByRole("combobox"), "high_accuracy");
    expect(screen.getByText(/High accuracy mode is slower/i)).toBeInTheDocument();
  });
});
