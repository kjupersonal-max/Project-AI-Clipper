import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClipCandidatesPanel } from "@/components/projects/ClipCandidatesPanel";
import { ExportedClipsPanel } from "@/components/projects/ExportedClipsPanel";
import type {
  ClipCandidate,
  ClipCandidatesDocument,
  ExportClipResponse,
} from "@/lib/api/projects";
import { defaultClipCandidateFilters } from "@/lib/clip-candidate-filters";

const candidate: ClipCandidate = {
  clip_id: "candidate-123",
  start: 10,
  end: 28,
  duration: 18,
  segment_ids: [1],
  transcript_text: "Sample transcript text.",
  score: 90,
  confidence: 0.95,
  primary_emotion: "excitement",
  hook_score: 92,
  payoff_score: 88,
  standalone_score: 85,
  context_dependency_score: 10,
  title_suggestion: "Sample clip title",
  reason: "Strong candidate.",
  status: "proposed",
};

const clipCandidates: ClipCandidatesDocument = {
  project_id: "project-1",
  candidate_count: 1,
  min_duration_seconds: 15,
  max_duration_seconds: 60,
  max_gap_seconds: 2,
  max_candidates: 8,
  source_duration_seconds: 300,
  candidates: [candidate],
  created_at: "2026-07-22T18:00:00Z",
};

const legacyExport: ExportClipResponse = {
  clip_id: "legacy-clip",
  project_id: "project-1",
  filename: "legacy.mp4",
  relative_path: "project-1/clips/legacy.mp4",
  media_url: "/api/projects/project-1/media/clips/legacy-clip",
  start_time: 1,
  end_time: 5,
  duration: 4,
  file_size_bytes: 1024,
  candidate_id: null,
  clip_name: "Legacy export",
  created_at: "2026-07-22T08:00:00Z",
  export_status: "completed",
  is_favorite: false,
};

const currentExport: ExportClipResponse = {
  clip_id: "current-clip",
  project_id: "project-1",
  filename: "current.mp4",
  relative_path: "project-1/clips/current.mp4",
  media_url: "/api/projects/project-1/media/clips/current-clip",
  start_time: 10,
  end_time: 28,
  duration: 18,
  file_size_bytes: 2048,
  candidate_id: "candidate-123",
  clip_name: "Current export",
  created_at: "2026-07-22T12:00:00Z",
  export_status: "completed",
  is_favorite: false,
};

afterEach(() => {
  cleanup();
});

describe("product workflow UI", () => {
  it("shows generate captions on final clip candidates", async () => {
    const user = userEvent.setup();
    const onGenerateCaptions = vi.fn();

    render(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        onGenerateCaptions={onGenerateCaptions}
      />,
    );

    await user.click(screen.getByRole("button", { name: /generate captions/i }));
    expect(onGenerateCaptions).toHaveBeenCalledWith(candidate);
  });

  it("shows caption status and retry on failure", () => {
    render(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        captionStates={{
          "candidate-123": {
            status: "failed",
            error: "Retranscription failed.",
          },
        }}
        onGenerateCaptions={() => undefined}
      />,
    );

    expect(screen.getByText("Caption generation failed")).toBeInTheDocument();
    expect(screen.getByText("Retranscription failed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry captions/i })).toBeEnabled();
  });

  it("separates legacy short exports from current exports", () => {
    render(<ExportedClipsPanel exportedClips={[currentExport, legacyExport]} />);

    expect(screen.getByText("Current export")).toBeInTheDocument();
    expect(screen.getByText("Legacy exports")).toBeInTheDocument();
    expect(screen.getAllByText("Legacy export").length).toBeGreaterThan(0);
  });
});
