from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.project import (
    ClipCandidate,
    ClipCandidateStatus,
    ImportanceBreakdown,
    SegmentAnalysis,
    TranscriptSegment,
)
from app.services.clip_importance import (
    assess_candidate_weakness,
    build_selection_reasons,
    compute_importance_breakdown,
    global_importance_selection,
    importance_total_score,
    transcript_overlap_ratio,
)
from app.services.clip_selection import select_project_clips
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import analyze_project_timeline


def _segment(
    segment_id: int,
    *,
    start: float,
    end: float,
    text: str,
    excitement: float = 0.0,
    humor: float = 0.0,
    suspense: float = 0.0,
    educational: float = 0.0,
    standalone: float = 5.0,
    context: float = 3.0,
    emotion: str = "neutral",
    clip_candidate: bool = True,
) -> SegmentAnalysis:
    return SegmentAnalysis(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        emotion=emotion,
        excitement_score=excitement,
        humor_score=humor,
        suspense_score=suspense,
        educational_score=educational,
        standalone_score=standalone,
        context_dependency_score=context,
        clip_candidate=clip_candidate,
        reason="test",
    )


def _candidate(
    *,
    clip_id: str,
    start: float,
    end: float,
    score: float,
    transcript_text: str,
    importance: ImportanceBreakdown,
    emotion: str = "neutral",
) -> ClipCandidate:
    return ClipCandidate(
        clip_id=clip_id,
        start=start,
        end=end,
        duration=round(end - start, 3),
        segment_ids=[0],
        transcript_text=transcript_text,
        score=score,
        confidence=0.7,
        primary_emotion=emotion,
        hook_score=5.0,
        payoff_score=5.0,
        standalone_score=6.0,
        context_dependency_score=3.0,
        title_suggestion=transcript_text[:40],
        reason="test",
        status=ClipCandidateStatus.PROPOSED,
        importance_breakdown=importance,
        selection_reasons=["test reason"],
    )


def test_weak_filler_is_rejected():
    segments = [
        _segment(0, start=0.0, end=18.0, text="okay yeah um you know like anyway", excitement=2.0, suspense=2.0)
    ]
    importance = compute_importance_breakdown(
        segments,
        hook_score=2.0,
        payoff_score=1.5,
        standalone_score=5.0,
        context_dependency_score=4.0,
        primary_emotion="neutral",
    )
    assessment = assess_candidate_weakness(
        segments,
        hook_score=2.0,
        payoff_score=1.5,
        standalone_score=5.0,
        context_dependency_score=4.0,
        importance=importance,
        total_score=45.0,
        min_score=40.0,
    )
    assert assessment.reject
    assert assessment.reason


def test_emotional_moment_outranks_generic_statement():
    emotional = compute_importance_breakdown(
        [
            _segment(
                0,
                start=0.0,
                end=5.0,
                text="No way, that clutch was insane!",
                excitement=8.5,
                suspense=7.0,
                emotion="excited",
            ),
            _segment(
                1,
                start=5.0,
                end=18.0,
                text="I cannot believe they pulled that off!",
                excitement=8.0,
                suspense=6.5,
                emotion="excited",
            ),
        ],
        hook_score=7.5,
        payoff_score=7.0,
        standalone_score=7.0,
        context_dependency_score=2.5,
        primary_emotion="excited",
    )
    generic = compute_importance_breakdown(
        [_segment(0, start=20.0, end=38.0, text="The game continues as expected.", excitement=3.0, suspense=2.5)],
        hook_score=2.5,
        payoff_score=2.0,
        standalone_score=6.0,
        context_dependency_score=3.0,
        primary_emotion="neutral",
    )
    assert importance_total_score(emotional) > importance_total_score(generic)


def test_setup_and_payoff_outranks_isolated_quote():
    arc = compute_importance_breakdown(
        [
            _segment(0, start=0.0, end=5.0, text="Wait, watch this setup.", suspense=6.5),
            _segment(1, start=5.0, end=12.0, text="They push forward aggressively.", excitement=6.0),
            _segment(2, start=12.0, end=18.0, text="And that is the clutch payoff!", excitement=7.5),
        ],
        hook_score=6.0,
        payoff_score=7.0,
        standalone_score=6.5,
        context_dependency_score=3.0,
        primary_emotion="excited",
    )
    quote = compute_importance_breakdown(
        [_segment(0, start=20.0, end=38.0, text="That was crazy!", excitement=7.0, suspense=4.0)],
        hook_score=6.5,
        payoff_score=2.0,
        standalone_score=5.5,
        context_dependency_score=4.0,
        primary_emotion="excited",
    )
    assert arc.story_value > quote.story_value
    assert importance_total_score(arc) > importance_total_score(quote)


def test_educational_value_can_rank_highly():
    educational = compute_importance_breakdown(
        [
            _segment(
                0,
                start=0.0,
                end=8.0,
                text="Because this tip helps you learn the mechanic clearly.",
                educational=8.0,
                emotion="informative",
            ),
            _segment(
                1,
                start=8.0,
                end=18.0,
                text="Here is how to execute the strategy step by step.",
                educational=7.5,
                emotion="informative",
            ),
        ],
        hook_score=4.5,
        payoff_score=6.0,
        standalone_score=7.5,
        context_dependency_score=2.0,
        primary_emotion="informative",
    )
    assert educational.information_value >= 6.0
    generic = compute_importance_breakdown(
        [_segment(0, start=0.0, end=18.0, text="The game continues.", educational=2.0)],
        hook_score=2.0,
        payoff_score=2.0,
        standalone_score=6.0,
        context_dependency_score=3.0,
        primary_emotion="neutral",
    )
    assert importance_total_score(educational) > importance_total_score(generic)


def test_duplicate_topics_are_reduced():
    strong = _candidate(
        clip_id="a",
        start=0.0,
        end=18.0,
        score=78.0,
        transcript_text="Kingling pulls off an insane 1v2 clutch in round one",
        importance=ImportanceBreakdown(
            hook=7.0,
            emotion=7.0,
            story_value=7.0,
            information_value=5.0,
            retention=6.0,
            shareability=6.0,
            standalone_quality=7.0,
            monetization_potential=6.0,
        ),
        emotion="excited",
    )
    duplicate = _candidate(
        clip_id="b",
        start=20.0,
        end=38.0,
        score=72.0,
        transcript_text="Kingling pulls off another insane 1v2 clutch in round one",
        importance=ImportanceBreakdown(
            hook=6.5,
            emotion=6.5,
            story_value=6.5,
            information_value=5.0,
            retention=5.5,
            shareability=5.5,
            standalone_quality=6.5,
            monetization_potential=5.5,
        ),
        emotion="excited",
    )
    selected, rejected = global_importance_selection(
        [strong, duplicate],
        max_count=8,
        quality_threshold=52.0,
        source_duration=300.0,
    )
    assert len(selected) == 1
    assert rejected
    assert any("similar" in item.rejection_reason.lower() for item in rejected)


def test_selector_may_return_fewer_than_eight():
    texts = [
        "Shadow push catches the enemy off guard for first blood",
        "Clutch defuse under heavy pressure saves the entire round",
        "Unexpected flank through mid turns the match upside down",
        "Final round ace closes out the map in dramatic fashion",
    ]
    candidates = [
        _candidate(
            clip_id=f"c{index}",
            start=float(index * 25),
            end=float(index * 25 + 18),
            score=58.0 + index,
            transcript_text=texts[index],
            importance=ImportanceBreakdown(
                hook=6.0,
                emotion=6.0,
                story_value=6.0,
                information_value=5.5,
                retention=5.5,
                shareability=5.5,
                standalone_quality=6.0,
                monetization_potential=5.5,
            ),
        )
        for index in range(4)
    ]
    selected, _ = global_importance_selection(
        candidates,
        max_count=8,
        quality_threshold=52.0,
        source_duration=300.0,
    )
    assert len(selected) == 4
    assert len(selected) < 8


def test_weak_video_may_return_zero_clips():
    weak = _candidate(
        clip_id="weak",
        start=0.0,
        end=18.0,
        score=48.0,
        transcript_text="okay yeah um anyway",
        importance=ImportanceBreakdown(
            hook=2.0,
            emotion=2.0,
            story_value=2.0,
            information_value=2.0,
            retention=2.0,
            shareability=2.0,
            standalone_quality=3.0,
            monetization_potential=2.5,
        ),
    )
    selected, rejected = global_importance_selection(
        [weak],
        max_count=8,
        quality_threshold=52.0,
        source_duration=60.0,
    )
    assert selected == []
    assert rejected


def test_final_reasons_match_score_signals():
    importance = ImportanceBreakdown(
        hook=7.0,
        emotion=7.5,
        story_value=7.0,
        information_value=6.5,
        retention=6.0,
        shareability=6.5,
        standalone_quality=7.0,
        monetization_potential=6.0,
    )
    reasons = build_selection_reasons(
        importance,
        hook_score=6.5,
        payoff_score=6.0,
        primary_emotion="excited",
    )
    assert reasons
    joined = " ".join(reasons).lower()
    assert "hook" in joined or "emotional" in joined or "arc" in joined or "information" in joined


def test_transcript_overlap_detects_similar_clips():
    first = _candidate(
        clip_id="1",
        start=0.0,
        end=18.0,
        score=70.0,
        transcript_text="Kingling wins the round with an insane clutch play",
        importance=ImportanceBreakdown(
            hook=6.0,
            emotion=6.0,
            story_value=6.0,
            information_value=5.0,
            retention=5.0,
            shareability=5.0,
            standalone_quality=6.0,
            monetization_potential=5.0,
        ),
    )
    second = _candidate(
        clip_id="2",
        start=20.0,
        end=38.0,
        score=68.0,
        transcript_text="Kingling wins the round with an insane clutch play again",
        importance=ImportanceBreakdown(
            hook=6.0,
            emotion=6.0,
            story_value=6.0,
            information_value=5.0,
            retention=5.0,
            shareability=5.0,
            standalone_quality=6.0,
            monetization_potential=5.0,
        ),
    )
    assert transcript_overlap_ratio(first, second) >= 0.7


def _write_completed_analysis(sample_project, temp_backend_dirs, segments: list[TranscriptSegment]):
    project_id = sample_project["project_id"]
    transcript_dir = temp_backend_dirs["transcripts_dir"] / project_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    from app.models.project import ProcessingStatus, TranscriptDocument

    document = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=max((segment.end for segment in segments), default=0.0),
        segment_count=len(segments),
        word_count=sum(len(segment.words) for segment in segments),
        segments=segments,
    )
    transcript_path = transcript_dir / "transcript.json"
    transcript_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")

    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.transcript_path = f"{project_id}/transcript.json"
    project.detected_language = "en"
    save_project(project)

    analysis = analyze_project_timeline(project_id)
    project = load_project(project_id)
    project.analysis_status = ProcessingStatus.COMPLETED
    project.analysis_path = f"{project_id}/analysis.json"
    project.analysis_provider = analysis.provider
    save_project(project)
    return analysis


def test_integration_final_count_at_most_ten_and_duration_at_least_fifteen(
    sample_project,
    temp_backend_dirs,
):
    segments = [
        TranscriptSegment(
            id=index,
            start=float(index * 4),
            end=float(index * 4 + 3.5),
            text=f"Wait insane clutch moment {index}! That was crazy!",
            words=[],
        )
        for index in range(40)
    ]
    _write_completed_analysis(sample_project, temp_backend_dirs, segments)
    document = select_project_clips(sample_project["project_id"], min_score=0.0)
    assert document.candidate_count <= settings.clip_selection_hard_max_candidates
    assert len(document.candidates) <= 10
    for candidate in document.candidates:
        assert candidate.duration >= settings.clip_selection_min_duration_seconds - 0.01
        assert candidate.importance_breakdown is not None
        assert candidate.selection_reasons
    assert document.selection_pipeline_version == settings.clip_selection_pipeline_version


def test_integration_weak_only_video_can_return_zero(sample_project, temp_backend_dirs):
    segments = [
        TranscriptSegment(id=0, start=0.0, end=20.0, text="okay yeah um you know", words=[]),
    ]
    _write_completed_analysis(sample_project, temp_backend_dirs, segments)
    document = select_project_clips(sample_project["project_id"], min_score=0.0)
    assert document.candidate_count == 0
