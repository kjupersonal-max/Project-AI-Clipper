from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.project import (
    ClipCandidate,
    ClipCandidateStatus,
    ProcessingStatus,
    SegmentAnalysis,
    TranscriptDocument,
    TranscriptSegment,
    VisualAnalysisDocument,
    VisualWindow,
)
from app.services.clip_boundary_refinement import refine_clip_segment_boundaries
from app.services.clip_importance import global_importance_selection
from app.services.clip_selection import _deduplicate_candidates, select_project_clips
from app.services.project_store import (
    get_visual_analysis_output_path,
    load_project,
    save_project,
)
from app.services.timeline_analysis import analyze_project_timeline, load_project_analysis
from app.services.visual_analysis import (
    VisualAnalysisUnavailableError,
    analyze_project_visuals,
    compute_video_fingerprint,
)
from app.services.visual_scoring import apply_visual_scoring, compute_visual_scoring_result


def _segment(
    segment_id: int,
    *,
    start: float,
    end: float,
    text: str,
    excitement: float = 5.0,
    standalone: float = 6.0,
) -> SegmentAnalysis:
    return SegmentAnalysis(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        emotion="excited",
        excitement_score=excitement,
        humor_score=0.0,
        suspense_score=0.0,
        educational_score=0.0,
        standalone_score=standalone,
        context_dependency_score=3.0,
        clip_candidate=True,
        reason="test",
    )


def _candidate(
    *,
    clip_id: str,
    start: float,
    end: float,
    score: float,
    payoff: float = 5.0,
    standalone: float = 6.0,
    duration_class: str = "short",
) -> ClipCandidate:
    return ClipCandidate(
        clip_id=clip_id,
        start=start,
        end=end,
        duration=round(end - start, 3),
        segment_ids=[0],
        transcript_text="That was insane!",
        score=score,
        confidence=0.7,
        primary_emotion="excited",
        hook_score=6.0,
        payoff_score=payoff,
        standalone_score=standalone,
        context_dependency_score=3.0,
        title_suggestion="Test clip",
        reason="Strong payoff",
        status=ClipCandidateStatus.PROPOSED,
        duration_class=duration_class,
        score_breakdown={"importance_total": score},
    )


def _visual_document(*, windows: list[VisualWindow]) -> VisualAnalysisDocument:
    return VisualAnalysisDocument(
        project_id="test",
        pipeline_version=settings.visual_analysis_pipeline_version,
        video_fingerprint="abc",
        processing_duration_seconds=1.0,
        sampled_frame_count=10,
        sample_interval_seconds=3.0,
        window_seconds=4.0,
        windows=windows,
    )


def test_cached_visual_analysis_is_reused(sample_project, monkeypatch):
    project_id = sample_project["project_id"]
    video_path = sample_project["video_path"]
    fingerprint = compute_video_fingerprint(video_path)

    project = load_project(project_id)
    project.inspection_status = ProcessingStatus.COMPLETED
    save_project(project)

    existing = VisualAnalysisDocument(
        project_id=project_id,
        pipeline_version=settings.visual_analysis_pipeline_version,
        video_fingerprint=fingerprint,
        processing_duration_seconds=2.5,
        sampled_frame_count=42,
        sample_interval_seconds=3.0,
        window_seconds=4.0,
        windows=[
            VisualWindow(
                start=0.0,
                end=4.0,
                motion_score=5.0,
                scene_change_score=4.0,
                activity_score=5.0,
                activity_label="medium",
            )
        ],
    )
    output_path = get_visual_analysis_output_path(project_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(existing.model_dump(mode="json")), encoding="utf-8")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Frame extraction should not run on cache hit")

    monkeypatch.setattr(
        "app.services.visual_analysis.extract_sampled_grayscale_frames",
        _fail_if_called,
    )

    document = analyze_project_visuals(project_id)
    assert document.sampled_frame_count == 42


def test_unavailable_visual_dependencies_fail_safely(monkeypatch):
    monkeypatch.setattr(settings, "visual_analysis_enabled", False)
    with pytest.raises(VisualAnalysisUnavailableError):
        analyze_project_visuals("missing-project")


def test_camera_cuts_alone_produce_negligible_contribution():
    document = _visual_document(
        windows=[
            VisualWindow(
                start=10.0,
                end=14.0,
                motion_score=2.0,
                scene_change_score=8.0,
                activity_score=3.0,
                activity_label="medium",
                events=["camera_cut"],
                peak_motion_timestamp=12.0,
            )
        ]
    )
    candidate = _candidate(
        clip_id="weak",
        start=10.0,
        end=20.0,
        score=40.0,
        payoff=2.0,
        standalone=3.0,
    )
    result = compute_visual_scoring_result(
        candidate,
        document,
        quality_threshold=52.0,
        apply_ranking=True,
    )
    assert result.visual_contribution == 0.0
    assert result.selection_rank_score == candidate.score


def test_limited_context_clips_cannot_receive_maximum_visual_boost():
    document = _visual_document(
        windows=[
            VisualWindow(
                start=80.0,
                end=84.0,
                motion_score=9.5,
                scene_change_score=9.0,
                activity_score=9.0,
                activity_label="high",
                events=["motion_spike"],
                peak_motion_timestamp=82.0,
            )
        ]
    )
    candidate = _candidate(
        clip_id="limited",
        start=80.0,
        end=95.0,
        score=58.0,
        payoff=2.0,
        standalone=3.0,
    )
    result = compute_visual_scoring_result(
        candidate,
        document,
        quality_threshold=52.0,
        apply_ranking=True,
    )
    assert result.visual_contribution == 0.0
    assert result.blocked_reason


def test_aligned_payoff_reaction_can_provide_small_boost():
    document = _visual_document(
        windows=[
            VisualWindow(
                start=118.0,
                end=122.0,
                motion_score=8.5,
                scene_change_score=6.0,
                activity_score=8.0,
                activity_label="high",
                events=["motion_spike"],
                peak_motion_timestamp=121.0,
            )
        ]
    )
    candidate = _candidate(
        clip_id="payoff",
        start=85.0,
        end=123.0,
        score=64.0,
        payoff=6.5,
        standalone=6.0,
    )
    result = compute_visual_scoring_result(
        candidate,
        document,
        quality_threshold=52.0,
        apply_ranking=True,
    )
    assert 0.0 < result.visual_contribution <= settings.visual_analysis_max_visual_boost
    assert result.selection_rank_score <= candidate.score + settings.visual_analysis_tie_breaker_max_boost
    assert result.evidence.alignment_reason


def test_visual_contribution_is_capped_and_cannot_cross_threshold():
    document = _visual_document(
        windows=[
            VisualWindow(
                start=0.0,
                end=4.0,
                motion_score=10.0,
                scene_change_score=10.0,
                activity_score=10.0,
                activity_label="high",
                events=["motion_spike"],
                peak_motion_timestamp=1.0,
            )
        ]
    )
    candidate = _candidate(
        clip_id="below",
        start=0.0,
        end=15.0,
        score=51.0,
        payoff=6.0,
        standalone=6.0,
    )
    result = compute_visual_scoring_result(
        candidate,
        document,
        quality_threshold=52.0,
        apply_ranking=True,
    )
    assert result.selection_rank_score == 51.0
    assert result.visual_contribution <= settings.visual_analysis_max_visual_boost


def test_deduplicate_prefers_narrative_arc_over_payoff_subclip():
    outer = _candidate(clip_id="arc", start=85.54, end=123.98, score=64.1, duration_class="medium")
    inner = _candidate(clip_id="sub", start=104.9, end=123.98, score=64.6, duration_class="short")
    kept = _deduplicate_candidates([inner, outer])
    assert len(kept) == 1
    assert kept[0].clip_id == "arc"


def test_marginal_additional_clip_is_rejected_after_three_strong_picks():
    strong = [
        _candidate(clip_id="a", start=10.0, end=30.0, score=64.0).model_copy(
            update={"transcript_text": "Opening hook lands hard."}
        ),
        _candidate(clip_id="b", start=80.0, end=120.0, score=63.0).model_copy(
            update={"transcript_text": "Mid-game fight breaks out."}
        ),
        _candidate(clip_id="c", start=700.0, end=720.0, score=58.0).model_copy(
            update={"transcript_text": "Late round clutch attempt."}
        ),
    ]
    marginal = _candidate(clip_id="d", start=620.0, end=645.0, score=54.4).model_copy(
        update={"transcript_text": "Brief impressed reaction mid-match."}
    )
    selected, rejected = global_importance_selection(
        [*strong, marginal],
        max_count=8,
        quality_threshold=52.0,
        source_duration=900.0,
    )
    assert len(selected) == 3
    assert all(item.clip_id in {"a", "b", "c"} for item in selected)
    assert any(item.clip_id == "d" for item in rejected)


def test_early_coverage_seed_group_is_included_when_missing_from_top_ranked():
    from app.services.clip_selection import _select_construction_seed_groups

    opening = [_segment(0, start=13.0, end=20.0, text="Opening hook", excitement=7.0)]
    later_opening = [_segment(1, start=35.0, end=42.0, text="Later setup", excitement=9.5)]
    late = [_segment(2, start=700.0, end=710.0, text="Late payoff", excitement=9.0)]
    filler_groups = [
        [_segment(index + 3, start=200.0 + index, end=205.0 + index, text=f"Mid {index}", excitement=10.0)]
        for index in range(12)
    ]
    groups = [opening, later_opening, *filler_groups, late]
    selected = _select_construction_seed_groups(groups, source_duration=900.0)
    assert any(abs(group[0].start - 13.0) < 0.05 for group in selected)


def test_visual_continuity_can_extend_an_early_ending():
    core = [
        _segment(0, start=80.0, end=84.0, text="Setup", excitement=5.0),
        _segment(1, start=84.2, end=86.0, text="No way!", excitement=8.0),
    ]
    tail = _segment(2, start=86.2, end=87.5, text="Oh my.", excitement=7.0)
    document = _visual_document(
        windows=[
            VisualWindow(
                start=85.0,
                end=88.0,
                motion_score=7.5,
                scene_change_score=5.0,
                activity_score=7.0,
                activity_label="high",
                events=["motion_spike"],
                peak_motion_timestamp=86.0,
            )
        ]
    )

    result = refine_clip_segment_boundaries(
        core,
        [*core, tail],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=40.0,
        visual_document=document,
    )

    assert result.segments[-1].end > core[-1].end
    assert result.segments[-1].end - core[-1].end <= settings.visual_analysis_visual_boundary_max_extension_seconds + 0.5


def test_unrelated_later_activity_is_not_pulled_into_clip():
    core = [_segment(0, start=10.0, end=14.0, text="Big moment!", excitement=8.0)]
    unrelated = _segment(1, start=30.0, end=34.0, text="Later action", excitement=9.0)
    document = _visual_document(
        windows=[
            VisualWindow(
                start=30.0,
                end=34.0,
                motion_score=9.5,
                scene_change_score=8.0,
                activity_score=9.0,
                activity_label="high",
                events=["motion_spike"],
                peak_motion_timestamp=31.0,
            )
        ]
    )

    result = refine_clip_segment_boundaries(
        core,
        [core[0], unrelated],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
        visual_document=document,
    )

    assert result.segments[-1].segment_id == core[-1].segment_id


def test_sync_analysis_flags_do_not_clear_seed_segments(sample_project, temp_backend_dirs, monkeypatch):
    project_id = sample_project["project_id"]
    _seed_transcript_and_analyze(project_id, temp_backend_dirs["transcripts_dir"])
    before = load_project_analysis(project_id)
    seed_count_before = sum(1 for segment in before.segments if segment.clip_candidate)

    monkeypatch.setattr(settings, "visual_analysis_ranking_mode", "disabled")
    monkeypatch.setattr(settings, "visual_analysis_enabled", False)
    select_project_clips(project_id)

    after = load_project_analysis(project_id)
    seed_count_after = sum(1 for segment in after.segments if segment.clip_candidate)
    assert seed_count_after == seed_count_before


def test_phase5_equivalent_selection_preserves_baseline_moments(
    sample_project,
    temp_backend_dirs,
    monkeypatch,
):
    project_id = sample_project["project_id"]
    _seed_transcript_and_analyze(project_id, temp_backend_dirs["transcripts_dir"])

    monkeypatch.setattr(settings, "visual_analysis_ranking_mode", "disabled")
    monkeypatch.setattr(settings, "visual_analysis_enabled", False)
    document = select_project_clips(project_id)

    assert document.candidate_count >= 0
    if document.candidates:
        for candidate in document.candidates:
            breakdown = candidate.score_breakdown or {}
            assert breakdown.get("visual_contribution", 0) in (0, 0.0, None)
            assert candidate.score == breakdown.get("transcript_only_score", candidate.score)


def test_shadow_mode_reports_without_changing_scores(monkeypatch):
    document = _visual_document(
        windows=[
            VisualWindow(
                start=118.0,
                end=122.0,
                motion_score=8.0,
                scene_change_score=6.0,
                activity_score=7.5,
                activity_label="high",
                events=["motion_spike"],
                peak_motion_timestamp=121.0,
            )
        ]
    )
    candidate = _candidate(clip_id="a", start=85.0, end=123.0, score=64.0, payoff=6.0)
    monkeypatch.setattr(settings, "visual_analysis_enabled", True)
    monkeypatch.setattr(settings, "visual_analysis_ranking_mode", "shadow")
    scored = apply_visual_scoring([candidate], document, quality_threshold=52.0)[0]
    assert scored.score == 64.0
    assert scored.score_breakdown.get("visual_shadow_mode") == 1.0


def _seed_transcript_and_analyze(project_id: str, transcripts_dir: Path) -> None:
    segments = [
        TranscriptSegment(id=0, start=0.0, end=5.0, text="Wait watch this.", words=[]),
        TranscriptSegment(id=1, start=5.2, end=12.0, text="No way that was insane!", words=[]),
        TranscriptSegment(id=2, start=12.2, end=20.0, text="Oh my god.", words=[]),
    ]
    document = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=20.0,
        segment_count=len(segments),
        word_count=10,
        segments=segments,
    )
    transcript_path = transcripts_dir / project_id / "transcript.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(json.dumps(document.model_dump(mode="json")), encoding="utf-8")

    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.transcript_path = f"{project_id}/transcript.json"
    project.inspection_status = ProcessingStatus.COMPLETED
    save_project(project)

    analyze_project_timeline(project_id)
    project = load_project(project_id)
    project.analysis_status = ProcessingStatus.COMPLETED
    save_project(project)
