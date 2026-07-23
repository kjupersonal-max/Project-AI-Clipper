from __future__ import annotations

import pytest

from app.models.project import SegmentAnalysis
from app.services.clip_boundary_refinement import (
    _ends_naturally,
    _is_filler_segment,
    _is_unrelated_tail,
    _needs_lead_in,
    _needs_post_payoff_tail,
    _payoff_segment_index,
    refine_clip_segment_boundaries,
)
from app.services.clip_selection import select_project_clips
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import analyze_project_timeline
from app.models.project import ProcessingStatus, TranscriptDocument, TranscriptSegment
import json


def _segment(
    segment_id: int,
    *,
    start: float,
    end: float,
    text: str,
    excitement: float = 5.0,
    humor: float = 0.0,
    suspense: float = 0.0,
    educational: float = 0.0,
    standalone: float = 6.0,
    context: float = 3.0,
    clip_candidate: bool = True,
) -> SegmentAnalysis:
    return SegmentAnalysis(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        emotion="excited",
        excitement_score=excitement,
        humor_score=humor,
        suspense_score=suspense,
        educational_score=educational,
        standalone_score=standalone,
        context_dependency_score=context,
        clip_candidate=clip_candidate,
        reason="test",
    )


def test_clip_does_not_end_immediately_after_payoff():
    core = [
        _segment(0, start=0.0, end=4.0, text="Wait, watch this setup", suspense=6.0),
        _segment(1, start=4.2, end=8.0, text="No way that clutch was insane", excitement=8.0),
    ]
    tail = _segment(2, start=8.3, end=10.5, text="Oh my god!", excitement=7.5)
    filler = _segment(3, start=10.7, end=14.0, text="okay yeah um anyway", excitement=1.0)

    result = refine_clip_segment_boundaries(
        core,
        [*core, tail, filler],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
    )

    assert result.segments[-1].segment_id == tail.segment_id
    assert result.segments[-1].end > core[-1].end
    assert any(adjustment.direction == "end" for adjustment in result.adjustments)


def test_natural_sentence_ending_is_preferred():
    complete = _segment(2, start=8.3, end=11.0, text="That was the cleanest play.", excitement=6.0)
    core = [
        _segment(0, start=0.0, end=4.0, text="They push the angle.", excitement=5.0),
        _segment(1, start=4.2, end=8.0, text="No way he hit that shot!", excitement=8.0),
    ]

    result = refine_clip_segment_boundaries(
        core,
        [*core, complete],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
    )

    assert result.segments[-1].text.endswith(".")
    assert result.segments[-1].segment_id == complete.segment_id


def test_short_reaction_tail_is_preserved():
    core = [
        _segment(0, start=0.0, end=5.0, text="He swings wide and misses.", excitement=4.0),
        _segment(1, start=5.2, end=9.0, text="And he gets the kill anyway!", excitement=8.0),
    ]
    reaction = _segment(2, start=9.2, end=11.0, text="Let's go!", excitement=7.0)

    result = refine_clip_segment_boundaries(
        core,
        [*core, reaction],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
    )

    assert reaction.segment_id in {segment.segment_id for segment in result.segments}
    assert result.segments[-1].end - core[-1].end >= 1.0


def test_unrelated_filler_is_not_included():
    core = [
        _segment(0, start=0.0, end=5.0, text="Huge team fight breaks out mid.", excitement=7.0),
        _segment(1, start=5.2, end=9.0, text="They win the round!", excitement=8.0),
    ]
    filler = _segment(2, start=9.2, end=12.0, text="okay yeah um you know", excitement=1.0)

    result = refine_clip_segment_boundaries(
        core,
        [*core, filler],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
        min_tail_seconds=1.0,
        max_tail_seconds=4.0,
    )

    assert filler.segment_id not in {segment.segment_id for segment in result.segments}


def test_strong_hook_is_not_buried_under_excessive_context():
    core = [
        _segment(
            1,
            start=5.0,
            end=10.0,
            text="No way, that was insane!",
            excitement=8.0,
            clip_candidate=True,
        ),
        _segment(2, start=10.2, end=18.0, text="They close it out perfectly.", excitement=6.0),
    ]
    setup = _segment(0, start=0.0, end=4.5, text="Earlier in the stream they were warming up.", excitement=2.0)

    result = refine_clip_segment_boundaries(
        core,
        [setup, *core],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
    )

    assert result.segments[0].segment_id == core[0].segment_id
    assert setup.segment_id not in {segment.segment_id for segment in result.segments}


def test_lead_in_added_when_context_is_needed():
    core = [
        _segment(
            1,
            start=5.0,
            end=10.0,
            text="And that is why it worked.",
            excitement=4.0,
            context=6.5,
            standalone=3.5,
            clip_candidate=False,
        ),
        _segment(2, start=10.2, end=18.0, text="The whole round flipped instantly!", excitement=7.0),
    ]
    setup = _segment(
        0,
        start=1.5,
        end=4.5,
        text="They bait the push and rotate fast.",
        excitement=5.0,
        standalone=6.0,
    )

    assert _needs_lead_in(core)
    result = refine_clip_segment_boundaries(
        core,
        [setup, *core],
        max_gap_seconds=2.5,
        context_padding_seconds=3.0,
        max_duration_seconds=30.0,
    )
    assert result.segments[0].segment_id == setup.segment_id
    assert any(adjustment.direction == "start" for adjustment in result.adjustments)


def test_payoff_index_prefers_late_peak():
    segments = [
        _segment(0, start=0.0, end=4.0, text="Setup", excitement=4.0),
        _segment(1, start=4.2, end=8.0, text="Mid fight", excitement=6.0),
        _segment(2, start=8.2, end=12.0, text="Huge kill!", excitement=8.5),
    ]
    assert _payoff_segment_index(segments) == 2


def test_ends_naturally_detects_punctuation():
    assert _ends_naturally("That was huge!")
    assert not _ends_naturally("and then he")


def test_selection_scores_and_count_remain_stable(sample_project, temp_backend_dirs):
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
    project_id = sample_project["project_id"]
    transcript_dir = temp_backend_dirs["transcripts_dir"] / project_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    document = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=max(segment.end for segment in segments),
        segment_count=len(segments),
        word_count=0,
        segments=segments,
    )
    (transcript_dir / "transcript.json").write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.transcript_path = f"{project_id}/transcript.json"
    save_project(project)
    analyze_project_timeline(project_id)
    project = load_project(project_id)
    project.analysis_status = ProcessingStatus.COMPLETED
    save_project(project)

    result = select_project_clips(project_id, min_score=0.0)
    assert result.candidate_count <= 10
    for candidate in result.candidates:
        assert candidate.duration >= 15.0
        assert candidate.score >= 0.0
