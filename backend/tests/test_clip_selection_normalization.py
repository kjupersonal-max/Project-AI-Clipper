from __future__ import annotations

import pytest

from app.models.project import SegmentAnalysis, TranscriptSegment
from app.services.clip_selection import (
    ClipSelectionOptions,
    _deduplicate_candidates,
    _normalize_candidate_segments,
    _validate_candidate_segments,
)
from app.models.project import ClipCandidate, ClipCandidateStatus


def _segment(
    segment_id: int,
    start: float,
    end: float,
    *,
    clip_candidate: bool = True,
) -> SegmentAnalysis:
    return SegmentAnalysis(
        segment_id=segment_id,
        start=start,
        end=end,
        text=f"Segment {segment_id}",
        emotion="excited",
        excitement_score=7.0,
        humor_score=6.0,
        suspense_score=5.0,
        educational_score=4.0,
        standalone_score=7.0,
        context_dependency_score=3.0,
        clip_candidate=clip_candidate,
        reason="test segment",
    )


def test_overlapping_segments_are_normalized_not_rejected():
    segments = [
        _segment(0, 0.0, 5.0),
        _segment(1, 4.5, 9.0),
    ]
    normalized = _normalize_candidate_segments(
        segments,
        source_duration=20.0,
        known_segment_ids={0, 1},
    )
    assert len(normalized) >= 1
    for left, right in zip(normalized, normalized[1:], strict=False):
        assert left.start <= right.start
        assert left.end <= right.start + 0.05 or left.end <= right.start


def test_validate_returns_sorted_segments():
    segments = [_segment(2, 10.0, 14.0), _segment(1, 5.0, 9.0)]
    normalized = _validate_candidate_segments(
        segments,
        source_duration=30.0,
        known_segment_ids={1, 2},
    )
    assert normalized[0].segment_id == 1


def test_invalid_timestamps_are_rejected():
    segments = [_segment(0, -1.0, 2.0)]
    normalized = _normalize_candidate_segments(
        segments,
        source_duration=10.0,
        known_segment_ids={0},
    )
    assert normalized == []


def test_overlapping_candidates_do_not_fail_request():
    candidates = [
        ClipCandidate(
            clip_id="a",
            start=0.0,
            end=20.0,
            duration=20.0,
            segment_ids=[0, 1],
            transcript_text="one",
            score=80.0,
            confidence=0.8,
            primary_emotion="excited",
            hook_score=7.0,
            payoff_score=7.0,
            standalone_score=7.0,
            context_dependency_score=3.0,
            title_suggestion="A",
            reason="A",
            status=ClipCandidateStatus.PROPOSED,
        ),
        ClipCandidate(
            clip_id="b",
            start=10.0,
            end=30.0,
            duration=20.0,
            segment_ids=[2, 3],
            transcript_text="two",
            score=60.0,
            confidence=0.7,
            primary_emotion="excited",
            hook_score=6.0,
            payoff_score=6.0,
            standalone_score=6.0,
            context_dependency_score=3.0,
            title_suggestion="B",
            reason="B",
            status=ClipCandidateStatus.PROPOSED,
        ),
    ]
    resolved = _deduplicate_candidates(candidates)
    assert len(resolved) == 1
    assert resolved[0].score == 80.0


def test_clip_selection_options_defaults():
    from app.services.clip_selection import resolve_selection_options

    options = resolve_selection_options()
    assert options.min_duration_seconds == 15.0
    assert options.preferred_min_duration_seconds == 15.0
    assert options.preferred_max_duration_seconds == 45.0
    assert options.max_duration_seconds == 120.0
