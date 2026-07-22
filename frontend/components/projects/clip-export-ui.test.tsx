import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClipCandidatesPanel } from "@/components/projects/ClipCandidatesPanel";
import { ExportedClipsPanel } from "@/components/projects/ExportedClipsPanel";
import { TimelineAnalysisPanel } from "@/components/projects/TimelineAnalysisPanel";
import type {
  AnalysisDocument,
  ClipCandidate,
  ClipCandidatesDocument,
  ExportClipResponse,
  SegmentAnalysis,
} from "@/lib/api/projects";
import { defaultClipCandidateFilters } from "@/lib/clip-candidate-filters";
import { defaultAnalysisFilters } from "@/lib/analysis-filters";

const candidate: ClipCandidate = {
  clip_id: "candidate-123",
  start: 10,
  end: 25,
  duration: 15,
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
  min_duration_seconds: 5,
  max_duration_seconds: 60,
  max_gap_seconds: 2,
  max_candidates: 10,
  source_duration_seconds: 300,
  candidates: [candidate],
  created_at: "2026-07-22T18:00:00Z",
};

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
};

const segment: SegmentAnalysis = {
  segment_id: 7,
  start: 10,
  end: 25,
  text: "Sample timeline segment text.",
  emotion: "excitement",
  excitement_score: 90,
  humor_score: 20,
  suspense_score: 15,
  educational_score: 30,
  standalone_score: 85,
  context_dependency_score: 10,
  clip_candidate: true,
  reason: "Strong candidate segment.",
};

const analysis: AnalysisDocument = {
  project_id: "project-1",
  provider: "heuristic",
  model: null,
  is_heuristic_fallback: true,
  segment_count: 2,
  clip_candidate_count: 1,
  segments: [
    segment,
    {
      ...segment,
      segment_id: 8,
      clip_candidate: false,
      text: "Non-candidate segment.",
    },
  ],
  created_at: "2026-07-22T18:00:00Z",
};

afterEach(() => {
  cleanup();
});

describe("ClipCandidatesPanel export UI", () => {
  it("disables export while exporting and prevents duplicate clicks", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();

    const { rerender } = render(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        exportStates={{ "candidate-123": { status: "exporting" } }}
        onExport={onExport}
      />,
    );

    const exportButton = screen.getByRole("button", { name: /exporting/i });
    expect(exportButton).toBeDisabled();

    await user.click(exportButton);
    expect(onExport).not.toHaveBeenCalled();

    rerender(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        exportStates={{ "candidate-123": { status: "completed" } }}
        exportedCandidateIds={new Set(["candidate-123"])}
        onExport={onExport}
      />,
    );

    expect(screen.getByRole("button", { name: /exported/i })).toBeDisabled();
    expect(screen.getAllByText("Exported").length).toBeGreaterThan(0);
  });

  it("shows restored exported state for candidate_id exports", () => {
    render(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        exportedCandidateIds={new Set(["candidate-123"])}
        exportStates={{ "candidate-123": { status: "completed" } }}
        onExport={() => undefined}
      />,
    );

    expect(screen.getByRole("button", { name: /exported/i })).toBeDisabled();
  });

  it("shows backend error messages for failed exports", () => {
    render(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        exportStates={{
          "candidate-123": {
            status: "failed",
            error: "Clip duration exceeds maximum allowed length.",
          },
        }}
        onExport={() => undefined}
      />,
    );

    expect(
      screen.getByText("Clip duration exceeds maximum allowed length."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry export/i })).toBeEnabled();
  });

  it("calls onExport when export is clicked", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();

    render(
      <ClipCandidatesPanel
        clipCandidates={clipCandidates}
        filters={defaultClipCandidateFilters}
        onFiltersChange={() => undefined}
        onSeek={() => undefined}
        onExport={onExport}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^export$/i }));
    expect(onExport).toHaveBeenCalledWith(candidate);
  });
});

describe("TimelineAnalysisPanel export UI", () => {
  it("shows Export only on clip candidate segments", () => {
    render(
      <TimelineAnalysisPanel
        analysis={analysis}
        filters={defaultAnalysisFilters}
        onSeek={() => undefined}
        onExportSegment={() => undefined}
      />,
    );

    expect(screen.getAllByRole("button", { name: /^export$/i })).toHaveLength(1);
  });

  it("calls onExportSegment when Export is clicked", async () => {
    const user = userEvent.setup();
    const onExportSegment = vi.fn();

    render(
      <TimelineAnalysisPanel
        analysis={analysis}
        filters={defaultAnalysisFilters}
        onSeek={() => undefined}
        onExportSegment={onExportSegment}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^export$/i }));
    expect(onExportSegment).toHaveBeenCalledWith(segment);
  });

  it("disables export while exporting", async () => {
    const user = userEvent.setup();
    const onExportSegment = vi.fn();

    render(
      <TimelineAnalysisPanel
        analysis={analysis}
        filters={defaultAnalysisFilters}
        onSeek={() => undefined}
        exportStates={{ "segment-7": { status: "exporting" } }}
        onExportSegment={onExportSegment}
      />,
    );

    const exportButton = screen.getByRole("button", { name: /exporting/i });
    expect(exportButton).toBeDisabled();
    await user.click(exportButton);
    expect(onExportSegment).not.toHaveBeenCalled();
  });
});

describe("ExportedClipsPanel", () => {
  it("renders exported clip metadata, preview, and download link", () => {
    const { container } = render(<ExportedClipsPanel exportedClips={[exportedClip]} />);

    expect(screen.getAllByText("Sample clip title").length).toBeGreaterThan(0);
    expect(screen.getByText("sample-clip-title.mp4")).toBeInTheDocument();
    expect(screen.getByText(/duration: 15s/i)).toBeInTheDocument();
    expect(screen.getByText(/size: 2.0 mb/i)).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();

    const video = container.querySelector("video");
    expect(video).toBeTruthy();
    expect(video?.getAttribute("src")).toBe(
      "http://localhost:8000/api/projects/project-1/media/clips/clip-1",
    );

    const downloadLink = screen.getByRole("link", { name: /download/i });
    expect(downloadLink).toHaveAttribute(
      "href",
      "http://localhost:8000/api/projects/project-1/media/clips/clip-1",
    );
    expect(downloadLink).toHaveAttribute("download", "sample-clip-title.mp4");
  });

  it("shows session-only empty state guidance", () => {
    render(<ExportedClipsPanel exportedClips={[]} />);

    expect(screen.getByText(/no exported clips yet/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/backend list endpoint is needed/i),
    ).not.toBeInTheDocument();
  });

  it("shows loading state", () => {
    render(<ExportedClipsPanel exportedClips={[]} loading />);

    expect(screen.getByText(/loading exported clips/i)).toBeInTheDocument();
  });

  it("shows API error state", () => {
    render(
      <ExportedClipsPanel
        exportedClips={[]}
        error="Unable to load exported clips."
      />,
    );

    expect(screen.getByText("Unable to load exported clips.")).toBeInTheDocument();
  });

  it("renames a clip successfully", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn().mockResolvedValue(undefined);

    const { rerender } = render(
      <ExportedClipsPanel
        exportedClips={[exportedClip]}
        onRename={onRename}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^rename$/i }));
    const input = screen.getByLabelText(/rename clip/i);
    await user.clear(input);
    await user.type(input, "Updated clip title");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onRename).toHaveBeenCalledWith("clip-1", "Updated clip title");

    rerender(
      <ExportedClipsPanel
        exportedClips={[{ ...exportedClip, clip_name: "Updated clip title" }]}
        onRename={onRename}
      />,
    );

    expect(screen.getByText("Updated clip title")).toBeInTheDocument();
  });

  it("prevents empty rename submission", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn().mockResolvedValue(undefined);

    render(
      <ExportedClipsPanel
        exportedClips={[exportedClip]}
        onRename={onRename}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^rename$/i }));
    const input = screen.getByLabelText(/rename clip/i);
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByText("Clip name cannot be empty.")).toBeInTheDocument();
  });

  it("shows rename API error", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn().mockRejectedValue({ message: "Unable to rename clip." });

    render(
      <ExportedClipsPanel
        exportedClips={[exportedClip]}
        onRename={onRename}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^rename$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText("Unable to rename clip.")).toBeInTheDocument();
  });

  it("shows delete confirmation with clip name", async () => {
    const user = userEvent.setup();

    render(
      <ExportedClipsPanel
        exportedClips={[exportedClip]}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    expect(
      screen.getByText(/delete "sample clip title"\?/i),
    ).toBeInTheDocument();
  });

  it("deletes a clip successfully", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);

    const { rerender } = render(
      <ExportedClipsPanel
        exportedClips={[exportedClip]}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /delete clip/i }));

    expect(onDelete).toHaveBeenCalledWith("clip-1");

    rerender(
      <ExportedClipsPanel
        exportedClips={[]}
        onDelete={onDelete}
      />,
    );

    expect(screen.getByText(/no exported clips yet/i)).toBeInTheDocument();
  });

  it("shows delete API error", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockRejectedValue({ message: "Unable to delete clip." });

    render(
      <ExportedClipsPanel
        exportedClips={[exportedClip]}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /delete clip/i }));

    expect(await screen.findByText("Unable to delete clip.")).toBeInTheDocument();
  });
});
