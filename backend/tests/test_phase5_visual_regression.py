from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.clip_selection import select_project_clips
from app.services.project_store import get_clip_candidates_output_dir
from app.services.timeline_analysis import analyze_project_timeline, has_existing_analysis_output


PHASE5_BASELINE = [
    (13.28, 33.74),
    (85.54, 123.98),
    (740.90, 761.78),
]

PROJECT_ID = "6dbfd514-90f0-4241-bf18-51c6de001ff2"


@pytest.mark.integration
@pytest.mark.no_clip_quality_mock
def test_phase5_baseline_project_regression():
    clip_dir = get_clip_candidates_output_dir(PROJECT_ID)
    if not clip_dir.parent.exists():
        pytest.skip("Baseline project artifacts are unavailable in this environment.")

    transcript_path = settings.transcripts_dir / PROJECT_ID / "discovery_transcript.json"
    if not transcript_path.exists():
        pytest.skip("Baseline project transcript is unavailable in this environment.")

    original_mode = settings.visual_analysis_ranking_mode
    original_enabled = settings.visual_analysis_enabled
    settings.visual_analysis_ranking_mode = "disabled"
    settings.visual_analysis_enabled = False

    try:
        if not has_existing_analysis_output(PROJECT_ID):
            analyze_project_timeline(PROJECT_ID)
        document = select_project_clips(PROJECT_ID)
    finally:
        settings.visual_analysis_ranking_mode = original_mode
        settings.visual_analysis_enabled = original_enabled

    selected_signatures = [(round(c.start, 2), round(c.end, 2)) for c in document.candidates]
    assert document.candidate_count == 3, selected_signatures
    for start, end in PHASE5_BASELINE:
        assert any(abs(s - start) < 0.05 and abs(e - end) < 0.05 for s, e in selected_signatures), (
            f"Missing Phase 5 baseline clip {start}->{end}; got {selected_signatures}"
        )

    assert not any(
        abs(c.start - 104.9) < 0.05 and abs(c.end - 123.98) < 0.05
        for c in document.candidates
    ), "Payoff-only subclip replaced the full mini-arc"
    assert not any(
        620.0 <= c.start <= 652.0 and c.score < settings.clip_selection_quality_threshold + 2.0
        for c in document.candidates
    ), "Marginal mid-video clip should not replace the Phase 5 baseline set"
