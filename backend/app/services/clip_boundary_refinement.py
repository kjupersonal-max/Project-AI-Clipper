from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.project import SegmentAnalysis, TranscriptSegment

FILLER_PATTERNS = (
    "okay",
    "yeah",
    "uh",
    "um",
    "like",
    "you know",
    "i mean",
    "so yeah",
    "anyway",
    "all right",
    "alright",
)


@dataclass(frozen=True)
class BoundaryAdjustment:
    direction: str
    seconds: float
    reason: str
    segment_id: int | None = None


@dataclass(frozen=True)
class BoundaryRefinementResult:
    segments: list[SegmentAnalysis]
    adjustments: list[BoundaryAdjustment]


def _segment_peak_engagement(segment: SegmentAnalysis) -> float:
    return max(
        segment.excitement_score,
        segment.humor_score,
        segment.suspense_score,
        segment.educational_score,
    )


def _ends_naturally(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[-1] in ".!?":
        return True
    return stripped.endswith("...")


def _word_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", text.lower()) if len(token) > 2}


def _token_overlap(first: str, second: str) -> float:
    first_tokens = _word_tokens(first)
    second_tokens = _word_tokens(second)
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / min(len(first_tokens), len(second_tokens))


def _clip_transcript(segments: list[SegmentAnalysis]) -> str:
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def _is_filler_segment(segment: SegmentAnalysis) -> bool:
    text = segment.text.lower().strip()
    words = re.findall(r"\b\w+\b", text)
    peak = _segment_peak_engagement(segment)
    if peak >= 5.5:
        return False
    filler_hits = sum(1 for pattern in FILLER_PATTERNS if pattern in text)
    if filler_hits >= 2 and peak < 4.5:
        return True
    if len(words) <= 2 and peak < 4.0:
        return True
    return False


def _is_unrelated_tail(
    candidate: SegmentAnalysis,
    core_segments: list[SegmentAnalysis],
) -> bool:
    core_text = _clip_transcript(core_segments)
    overlap = _token_overlap(core_text, candidate.text)
    peak = _segment_peak_engagement(candidate)
    if overlap < 0.08 and peak < 5.0:
        return True
    if candidate.context_dependency_score >= 7.0 and peak < 4.5:
        return True
    return False


def _is_acceptable_tail_segment(
    candidate: SegmentAnalysis,
    core_segments: list[SegmentAnalysis],
    payoff_segment: SegmentAnalysis,
) -> bool:
    words = re.findall(r"\b\w+\b", candidate.text)
    payoff_peak = _segment_peak_engagement(payoff_segment)
    if payoff_peak >= 6.0 and _ends_naturally(candidate.text) and len(words) >= 2:
        return True
    if _is_unrelated_tail(candidate, core_segments):
        return False
    peak = _segment_peak_engagement(candidate)
    if peak >= 4.0:
        return True
    return not _is_filler_segment(candidate)


def _payoff_segment_index(segments: list[SegmentAnalysis]) -> int:
    if len(segments) == 1:
        return 0
    best_index = len(segments) - 1
    best_score = float("-inf")
    for index, segment in enumerate(segments):
        peak = _segment_peak_engagement(segment)
        position_bonus = (index / max(len(segments) - 1, 1)) * 2.0
        score = peak + position_bonus
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _ordered_segments_by_id(
    segments: list[SegmentAnalysis],
) -> dict[int, SegmentAnalysis]:
    return {segment.segment_id: segment for segment in segments}


def _needs_post_payoff_tail(
    core_segments: list[SegmentAnalysis],
    *,
    min_tail_seconds: float,
) -> bool:
    if not core_segments:
        return False
    payoff_index = _payoff_segment_index(core_segments)
    payoff_segment = core_segments[payoff_index]
    last_segment = core_segments[-1]
    tail_after_payoff = last_segment.end - payoff_segment.end
    if payoff_index == len(core_segments) - 1:
        if not _ends_naturally(last_segment.text):
            return True
        if _segment_peak_engagement(last_segment) >= 6.0:
            return tail_after_payoff < min_tail_seconds
        return False
    if tail_after_payoff < min_tail_seconds:
        return True
    if not _ends_naturally(last_segment.text):
        return True
    return False


def _extend_post_payoff_tail(
    core_segments: list[SegmentAnalysis],
    all_segments: list[SegmentAnalysis],
    *,
    max_gap_seconds: float,
    context_padding_seconds: float,
    max_duration_seconds: float,
    min_tail_seconds: float,
    max_tail_seconds: float,
) -> tuple[list[SegmentAnalysis], list[BoundaryAdjustment]]:
    if not _needs_post_payoff_tail(core_segments, min_tail_seconds=min_tail_seconds):
        return core_segments, []

    by_id = _ordered_segments_by_id(all_segments)
    selected_ids = {segment.segment_id for segment in core_segments}
    payoff_index = _payoff_segment_index(core_segments)
    payoff_segment = core_segments[payoff_index]
    adjustments: list[BoundaryAdjustment] = []
    selected = list(core_segments)

    next_id = max(selected_ids) + 1
    tail_from_payoff = selected[-1].end - payoff_segment.end

    while tail_from_payoff < max_tail_seconds:
        next_segment = by_id.get(next_id)
        if next_segment is None:
            break

        gap = next_segment.start - selected[-1].end
        if gap > max_gap_seconds + context_padding_seconds:
            break

        projected_duration = next_segment.end - selected[0].start
        if projected_duration > max_duration_seconds:
            break

        if not _is_acceptable_tail_segment(next_segment, core_segments, payoff_segment):
            break

        selected.append(next_segment)
        selected_ids.add(next_segment.segment_id)
        tail_from_payoff = next_segment.end - payoff_segment.end
        adjustments.append(
            BoundaryAdjustment(
                direction="end",
                seconds=round(next_segment.end - core_segments[-1].end, 3),
                reason="Extended past payoff for natural sentence or reaction tail",
                segment_id=next_segment.segment_id,
            )
        )
        next_id += 1

        if _ends_naturally(next_segment.text) and tail_from_payoff >= min_tail_seconds:
            break
        if tail_from_payoff >= max_tail_seconds:
            break

    return selected, adjustments


def _needs_lead_in(core_segments: list[SegmentAnalysis]) -> bool:
    if not core_segments:
        return False
    first = core_segments[0]
    peak = _segment_peak_engagement(first)
    if first.clip_candidate and peak >= 6.0:
        return False
    if peak >= 6.5:
        return False
    if first.standalone_score >= 6.0 and first.context_dependency_score <= 3.5:
        return False
    return (
        first.context_dependency_score >= 5.0
        or first.standalone_score < 4.5
        or (not first.clip_candidate and peak < 5.0)
    )


def _maybe_add_lead_in(
    segments: list[SegmentAnalysis],
    all_segments: list[SegmentAnalysis],
    *,
    max_gap_seconds: float,
    context_padding_seconds: float,
    max_duration_seconds: float,
    max_lead_in_seconds: float,
) -> tuple[list[SegmentAnalysis], list[BoundaryAdjustment]]:
    core_segments = segments
    if not _needs_lead_in(core_segments):
        return segments, []

    by_id = _ordered_segments_by_id(all_segments)
    first = core_segments[0]
    previous = by_id.get(first.segment_id - 1)
    if previous is None:
        return segments, []

    gap = first.start - previous.end
    if gap > max_gap_seconds + context_padding_seconds:
        return segments, []

    lead_in_seconds = first.start - previous.start
    if lead_in_seconds > max_lead_in_seconds:
        return segments, []

    if _is_filler_segment(previous):
        return segments, []

    projected_duration = core_segments[-1].end - previous.start
    if projected_duration > max_duration_seconds:
        return segments, []

    if _segment_peak_engagement(previous) >= _segment_peak_engagement(first) + 2.0:
        return segments, []

    return [previous, *core_segments], [
        BoundaryAdjustment(
            direction="start",
            seconds=round(first.start - previous.start, 3),
            reason="Added brief lead-in for standalone context",
            segment_id=previous.segment_id,
        )
    ]


def refine_clip_segment_boundaries(
    core_segments: list[SegmentAnalysis],
    all_segments: list[SegmentAnalysis],
    *,
    max_gap_seconds: float,
    context_padding_seconds: float,
    max_duration_seconds: float,
    min_tail_seconds: float = 1.0,
    max_tail_seconds: float = 4.0,
    max_lead_in_seconds: float = 4.0,
) -> BoundaryRefinementResult:
    if not core_segments:
        return BoundaryRefinementResult(segments=[], adjustments=[])

    with_tail, tail_adjustments = _extend_post_payoff_tail(
        core_segments,
        all_segments,
        max_gap_seconds=max_gap_seconds,
        context_padding_seconds=context_padding_seconds,
        max_duration_seconds=max_duration_seconds,
        min_tail_seconds=min_tail_seconds,
        max_tail_seconds=max_tail_seconds,
    )
    refined, lead_adjustments = _maybe_add_lead_in(
        with_tail,
        all_segments,
        max_gap_seconds=max_gap_seconds,
        context_padding_seconds=context_padding_seconds,
        max_duration_seconds=max_duration_seconds,
        max_lead_in_seconds=max_lead_in_seconds,
    )
    return BoundaryRefinementResult(
        segments=refined,
        adjustments=[*lead_adjustments, *tail_adjustments],
    )
