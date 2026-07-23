from __future__ import annotations

import json
import logging
import math
import shutil
import time
import uuid
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.config import settings
from app.models.project import (
    AnalysisDocument,
    ClipCandidate,
    ClipCandidateStatus,
    ClipCandidatesDocument,
    ProcessingStatus,
    SegmentAnalysis,
    TranscriptDocument,
    TranscriptSegment,
)
from app.services.pipeline_timing import log_stage_event, log_timing_summary
from app.services.clip_boundary_refinement import refine_clip_segment_boundaries
from app.services.clip_importance import (
    assess_candidate_weakness,
    build_human_reason,
    build_selection_reasons,
    build_selection_warnings,
    compute_importance_breakdown,
    empty_visual_evidence,
    global_importance_selection,
    importance_breakdown_to_score_dict,
    importance_total_score,
)
from app.services.project_store import (
    get_clip_candidates_output_dir,
    get_clip_candidates_output_path,
    get_relative_clip_candidates_path,
    load_project,
    save_project,
)
from app.services.timeline_analysis import (
    AnalysisNotFoundError,
    AnalysisProcessError,
    load_project_analysis,
)
from app.services.transcription import (
    TranscriptNotFoundError,
    TranscriptionProcessError,
    load_project_transcript,
)
from app.services.transcript_store import load_workflow_transcript
from app.services.visual_analysis import try_load_project_visual_analysis
from app.services.visual_scoring import apply_visual_scoring, should_apply_visual_boundaries

logger = logging.getLogger(__name__)


class ClipSelectionTranscriptRequiredError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipSelectionAnalysisRequiredError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidAnalysisForSelectionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipSelectionProcessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipCandidatesNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ClipDurationClass:
    label: str
    min_seconds: float
    max_seconds: float


def _duration_classes() -> list[ClipDurationClass]:
    return [
        ClipDurationClass("short", settings.clip_selection_short_min_seconds, settings.clip_selection_short_max_seconds),
        ClipDurationClass("medium", settings.clip_selection_medium_min_seconds, settings.clip_selection_medium_max_seconds),
        ClipDurationClass("long", settings.clip_selection_long_min_seconds, settings.clip_selection_long_max_seconds),
    ]


@dataclass(frozen=True)
class ClipSelectionOptions:
    min_duration_seconds: float
    preferred_min_duration_seconds: float
    preferred_max_duration_seconds: float
    max_duration_seconds: float
    max_gap_seconds: float
    max_candidates: int
    min_score: float
    context_padding_seconds: float


def _sanitize_error_message(message: str, max_length: int = 240) -> str:
    cleaned = " ".join(message.strip().split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3] + "..."


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _round_score(value: float, digits: int = 1) -> float:
    return round(_clamp(value, 0.0, 10.0), digits)


def cleanup_clip_candidates_output(project_id: str) -> None:
    clip_dir = settings.clip_candidates_dir / project_id
    partial_path = clip_dir / f"{settings.clip_candidates_output_filename}.part"
    if partial_path.exists():
        partial_path.unlink(missing_ok=True)

    output_path = clip_dir / settings.clip_candidates_output_filename
    if output_path.exists():
        output_path.unlink(missing_ok=True)

    if clip_dir.exists() and not any(clip_dir.iterdir()):
        shutil.rmtree(clip_dir, ignore_errors=True)


def resolve_selection_options(
    *,
    min_duration_seconds: float | None = None,
    max_duration_seconds: float | None = None,
    max_gap_seconds: float | None = None,
    max_candidates: int | None = None,
    min_score: float | None = None,
) -> ClipSelectionOptions:
    resolved_min = min_duration_seconds or settings.clip_selection_min_duration_seconds
    resolved_preferred_min = settings.clip_selection_preferred_min_duration_seconds
    resolved_preferred_max = settings.clip_selection_preferred_max_duration_seconds
    resolved_max = max_duration_seconds or settings.clip_selection_max_duration_seconds
    resolved_gap = max_gap_seconds or settings.clip_selection_max_gap_seconds
    resolved_max_candidates = max_candidates or settings.clip_selection_max_candidates
    resolved_min_score = min_score if min_score is not None else settings.clip_selection_min_score
    resolved_context_padding = settings.clip_selection_context_padding_seconds

    if resolved_min <= 0:
        raise ClipSelectionProcessError("Minimum clip duration must be greater than zero.")
    if resolved_max <= resolved_min:
        raise ClipSelectionProcessError(
            "Maximum clip duration must be greater than minimum duration."
        )
    if resolved_gap < 0:
        raise ClipSelectionProcessError("Maximum segment gap cannot be negative.")
    if resolved_max_candidates <= 0:
        raise ClipSelectionProcessError("Maximum candidate count must be greater than zero.")
    resolved_max_candidates = min(
        resolved_max_candidates,
        settings.clip_selection_hard_max_candidates,
    )
    if not 0.0 <= resolved_min_score <= 100.0:
        raise ClipSelectionProcessError("Minimum score must be between 0 and 100.")

    return ClipSelectionOptions(
        min_duration_seconds=resolved_min,
        preferred_min_duration_seconds=resolved_preferred_min,
        preferred_max_duration_seconds=resolved_preferred_max,
        max_duration_seconds=resolved_max,
        max_gap_seconds=resolved_gap,
        max_candidates=resolved_max_candidates,
        min_score=resolved_min_score,
        context_padding_seconds=resolved_context_padding,
    )


def _require_completed_inputs(project_id: str) -> tuple[TranscriptDocument, AnalysisDocument]:
    project = load_project(project_id)
    if project.transcription_status.value != "completed":
        raise ClipSelectionTranscriptRequiredError(
            "Transcription must be completed before clip selection."
        )
    if project.analysis_status.value != "completed":
        raise ClipSelectionAnalysisRequiredError(
            "Timeline analysis must be completed before clip selection."
        )

    try:
        transcript = load_workflow_transcript(project_id)
    except TranscriptNotFoundError as exc:
        raise ClipSelectionTranscriptRequiredError(exc.message) from exc
    except TranscriptionProcessError as exc:
        raise ClipSelectionTranscriptRequiredError(exc.message) from exc

    if not transcript.segments:
        raise ClipSelectionTranscriptRequiredError("Transcript contains no segments.")

    try:
        analysis = load_project_analysis(project_id)
    except AnalysisNotFoundError as exc:
        raise ClipSelectionAnalysisRequiredError(exc.message) from exc
    except AnalysisProcessError as exc:
        raise ClipSelectionAnalysisRequiredError(exc.message) from exc

    if not analysis.segments:
        raise InvalidAnalysisForSelectionError("Analysis contains no segments.")

    if len(transcript.segments) != len(analysis.segments):
        raise InvalidAnalysisForSelectionError(
            "Analysis segment count does not match transcript segment count."
        )

    for source, result in zip(transcript.segments, analysis.segments, strict=True):
        if result.segment_id != source.id:
            raise InvalidAnalysisForSelectionError(
                f"Analysis segment_id mismatch for transcript segment {source.id}."
            )

    return transcript, analysis


def _source_duration(
    transcript: TranscriptDocument,
    analysis: AnalysisDocument,
    project_id: str,
) -> float:
    project = load_project(project_id)
    if project.video_metadata and project.video_metadata.duration_seconds:
        return project.video_metadata.duration_seconds
    if transcript.duration > 0:
        return transcript.duration
    if analysis.segments:
        return max(segment.end for segment in analysis.segments)
    return 0.0


def _segment_strength(segment: SegmentAnalysis) -> float:
    peak = max(
        segment.excitement_score,
        segment.humor_score,
        segment.suspense_score,
        segment.educational_score,
    )
    average = (
        segment.excitement_score
        + segment.humor_score
        + segment.suspense_score
        + segment.educational_score
    ) / 4.0
    standalone_bonus = segment.standalone_score * 0.35
    context_penalty = segment.context_dependency_score * 0.25
    candidate_bonus = 2.0 if segment.clip_candidate else 0.0
    return peak + average * 0.5 + standalone_bonus + candidate_bonus - context_penalty


def _group_seed_segments(
    segments: list[SegmentAnalysis],
    max_gap_seconds: float,
) -> list[list[SegmentAnalysis]]:
    seeds = [segment for segment in segments if segment.clip_candidate]
    if not seeds:
        return []

    seeds.sort(key=lambda segment: segment.segment_id)
    groups: list[list[SegmentAnalysis]] = []
    current: list[SegmentAnalysis] = []

    for seed in seeds:
        if not current:
            current = [seed]
            continue

        previous = current[-1]
        gap = seed.start - previous.end
        if gap <= max_gap_seconds:
            current.append(seed)
        else:
            groups.append(current)
            current = [seed]

    if current:
        groups.append(current)

    return groups


def _ordered_segments_by_id(
    segments: list[SegmentAnalysis],
) -> dict[int, SegmentAnalysis]:
    return {segment.segment_id: segment for segment in segments}


def _expand_group_segments(
    group: list[SegmentAnalysis],
    all_segments: list[SegmentAnalysis],
    options: ClipSelectionOptions,
    transcript_segments: dict[int, TranscriptSegment],
) -> list[SegmentAnalysis]:
    by_id = _ordered_segments_by_id(all_segments)
    min_id = min(segment.segment_id for segment in group)
    max_id = max(segment.segment_id for segment in group)
    selected_ids = {segment.segment_id for segment in group}

    def selected_segments() -> list[SegmentAnalysis]:
        return [by_id[segment_id] for segment_id in sorted(selected_ids) if segment_id in by_id]

    def current_duration() -> float:
        ordered = selected_segments()
        if not ordered:
            return 0.0
        return ordered[-1].end - ordered[0].start

    target_duration = max(options.min_duration_seconds, options.preferred_min_duration_seconds)

    while current_duration() < target_duration:
        previous_id = min_id - 1
        next_id = max_id + 1
        previous_segment = by_id.get(previous_id)
        next_segment = by_id.get(next_id)
        candidates: list[tuple[float, SegmentAnalysis, str]] = []

        if previous_segment is not None:
            gap = selected_segments()[0].start - previous_segment.end
            if gap <= options.max_gap_seconds + options.context_padding_seconds:
                projected = selected_segments()[-1].end - previous_segment.start
                if projected <= options.max_duration_seconds:
                    bonus = 1.5 if "?" in previous_segment.text else 0.0
                    candidates.append(
                        (_segment_strength(previous_segment) + bonus, previous_segment, "prev")
                    )

        if next_segment is not None:
            gap = next_segment.start - selected_segments()[-1].end
            if gap <= options.max_gap_seconds + options.context_padding_seconds:
                projected = next_segment.end - selected_segments()[0].start
                if projected <= options.max_duration_seconds:
                    bonus = 2.0 if any(
                        "?" in segment.text for segment in selected_segments()
                    ) else 0.0
                    candidates.append(
                        (_segment_strength(next_segment) + bonus, next_segment, "next")
                    )

        if not candidates:
            break

        _, chosen, direction = max(candidates, key=lambda item: item[0])
        selected_ids.add(chosen.segment_id)
        if direction == "prev":
            min_id = chosen.segment_id
        else:
            max_id = chosen.segment_id

    return _normalize_candidate_segments(
        selected_segments(),
        known_segment_ids=set(by_id),
        source_duration=float("inf"),
    )


def _trim_group_to_max_duration(
    segments: list[SegmentAnalysis],
    options: ClipSelectionOptions,
) -> list[SegmentAnalysis]:
    if not segments:
        return segments

    start = segments[0].start
    end = segments[-1].end
    if end - start <= options.max_duration_seconds:
        return segments

    best_window: list[SegmentAnalysis] | None = None
    best_strength = float("-inf")

    for left in range(len(segments)):
        for right in range(left, len(segments)):
            window = segments[left : right + 1]
            duration = window[-1].end - window[0].start
            if duration > options.max_duration_seconds:
                continue
            strength = sum(_segment_strength(segment) for segment in window) / len(window)
            if strength > best_strength:
                best_strength = strength
                best_window = window

    return best_window or [max(segments, key=_segment_strength)]


def _dominant_emotion(segments: list[SegmentAnalysis]) -> str:
    weights: dict[str, float] = {}
    for segment in segments:
        weights[segment.emotion] = weights.get(segment.emotion, 0.0) + _segment_strength(segment)
    return max(weights, key=weights.get)


def _hook_score(segments: list[SegmentAnalysis]) -> float:
    first = segments[0]
    return _round_score(
        first.excitement_score * 0.45
        + first.humor_score * 0.25
        + first.suspense_score * 0.2
        + first.standalone_score * 0.1
    )


def _payoff_score(segments: list[SegmentAnalysis]) -> float:
    last = segments[-1]
    return _round_score(
        last.excitement_score * 0.35
        + last.humor_score * 0.2
        + last.suspense_score * 0.25
        + last.educational_score * 0.2
    )


def _average_score(segments: list[SegmentAnalysis], attribute: str) -> float:
    values = [getattr(segment, attribute) for segment in segments]
    return _round_score(sum(values) / len(values))


def _compute_candidate_score(
    segments: list[SegmentAnalysis],
    *,
    hook_score: float,
    payoff_score: float,
    standalone_score: float,
    context_dependency_score: float,
    duration: float,
    options: ClipSelectionOptions,
) -> tuple[float, dict[str, float]]:
    peak_engagement = max(
        max(segment.excitement_score for segment in segments),
        max(segment.humor_score for segment in segments),
        max(segment.suspense_score for segment in segments),
        max(segment.educational_score for segment in segments),
    )
    average_engagement = sum(
        (
            segment.excitement_score
            + segment.humor_score
            + segment.suspense_score
            + segment.educational_score
        )
        / 4.0
        for segment in segments
    ) / len(segments)

    completeness_bonus = min(10.0, standalone_score * 0.8 + payoff_score * 0.4)
    educational_avg = _average_score(segments, "educational_score")
    retention_score = _round_score(payoff_score * 0.6 + (10.0 - context_dependency_score) * 0.4)
    engagement_score = _round_score((peak_engagement + average_engagement) / 2.0)
    monetization_potential = _round_score(
        standalone_score * 0.35
        + educational_avg * 0.25
        + hook_score * 0.2
        + (10.0 - context_dependency_score) * 0.2
    )
    duration_quality = 0.0
    if options.preferred_min_duration_seconds <= duration <= options.preferred_max_duration_seconds:
        duration_quality = 8.0
    elif duration < options.min_duration_seconds:
        duration_quality = -100.0
    elif duration < options.preferred_min_duration_seconds:
        duration_quality = max(-12.0, (duration - options.preferred_min_duration_seconds) * 0.8)
    elif duration > options.preferred_max_duration_seconds:
        duration_quality = max(-8.0, (options.preferred_max_duration_seconds - duration) * 0.25)

    score = (
        hook_score * 4.5
        + payoff_score * 3.5
        + standalone_score * 4.0
        + peak_engagement * 2.5
        + average_engagement * 2.0
        + completeness_bonus
        + duration_quality
        - context_dependency_score * 3.0
    )
    normalized = (score / 78.0) * 100.0
    breakdown = {
        "hook": round(hook_score * 4.5, 2),
        "payoff": round(payoff_score * 3.5, 2),
        "standalone": round(standalone_score * 4.0, 2),
        "engagement": round((peak_engagement * 2.5 + average_engagement * 2.0), 2),
        "retention": round(retention_score * 2.0, 2),
        "completeness": round(completeness_bonus, 2),
        "monetization_potential": round(monetization_potential * 1.5, 2),
        "duration_quality": round(duration_quality, 2),
        "context_penalty": round(context_dependency_score * 3.0, 2),
    }
    return round(_clamp(normalized, 0.0, 100.0), 1), breakdown


def _compute_confidence(
    segments: list[SegmentAnalysis],
    *,
    score: float,
    standalone_score: float,
    context_dependency_score: float,
) -> float:
    candidate_ratio = sum(1 for segment in segments if segment.clip_candidate) / len(segments)
    consistency = sum(
        1.0
        - (
            max(
                segment.excitement_score,
                segment.humor_score,
                segment.suspense_score,
                segment.educational_score,
            )
            - min(
                segment.excitement_score,
                segment.humor_score,
                segment.suspense_score,
                segment.educational_score,
            )
        )
        / 10.0
        for segment in segments
    ) / len(segments)

    confidence = (
        (score / 100.0) * 0.45
        + (standalone_score / 10.0) * 0.25
        + candidate_ratio * 0.2
        + consistency * 0.15
        - (context_dependency_score / 10.0) * 0.15
    )
    return round(_clamp(confidence, 0.0, 1.0), 2)


def _build_title_suggestion(segments: list[SegmentAnalysis], primary_emotion: str) -> str:
    lead = segments[0].text.strip()
    if len(lead) > 64:
        lead = lead[:61].rstrip() + "..."
    if lead:
        return lead
    return f"{primary_emotion.title()} moment"


def _build_reason(
    segments: list[SegmentAnalysis],
    *,
    hook_score: float,
    payoff_score: float,
    standalone_score: float,
    context_dependency_score: float,
    primary_emotion: str,
) -> str:
    drivers = []
    peak_excitement = max(segment.excitement_score for segment in segments)
    peak_humor = max(segment.humor_score for segment in segments)
    peak_suspense = max(segment.suspense_score for segment in segments)
    peak_educational = max(segment.educational_score for segment in segments)

    if peak_excitement >= 6.0:
        drivers.append(f"excitement {peak_excitement:.1f}/10")
    if peak_humor >= 6.0:
        drivers.append(f"humor {peak_humor:.1f}/10")
    if peak_suspense >= 6.0:
        drivers.append(f"suspense {peak_suspense:.1f}/10")
    if peak_educational >= 6.0:
        drivers.append(f"educational value {peak_educational:.1f}/10")

    driver_text = ", ".join(drivers) if drivers else "balanced segment engagement"
    return (
        f"Grouped {len(segments)} nearby strong segments into a {primary_emotion} clip "
        f"with {driver_text}. Hook {hook_score:.1f}/10, payoff {payoff_score:.1f}/10, "
        f"standalone {standalone_score:.1f}/10, context dependency "
        f"{context_dependency_score:.1f}/10."
    )


def _build_transcript_text(
    segments: list[SegmentAnalysis],
    transcript_segments: dict[int, TranscriptSegment],
) -> str:
    parts = []
    for segment in segments:
        transcript_segment = transcript_segments.get(segment.segment_id)
        text = transcript_segment.text.strip() if transcript_segment else segment.text.strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _normalize_candidate_segments(
    segments: list[SegmentAnalysis],
    *,
    source_duration: float,
    known_segment_ids: set[int],
) -> list[SegmentAnalysis]:
    if not segments:
        return []

    valid: list[SegmentAnalysis] = []
    for segment in segments:
        if segment.segment_id not in known_segment_ids:
            logger.warning("Dropping unknown segment id=%s from candidate", segment.segment_id)
            continue
        if not math.isfinite(segment.start) or not math.isfinite(segment.end):
            logger.warning("Dropping invalid timing for segment id=%s", segment.segment_id)
            continue
        if segment.start < 0 or segment.end <= segment.start:
            logger.warning("Dropping non-positive segment id=%s", segment.segment_id)
            continue
        if source_duration > 0 and segment.start >= source_duration:
            continue
        clamped_end = min(segment.end, source_duration) if source_duration > 0 else segment.end
        if clamped_end <= segment.start:
            continue
        if clamped_end != segment.end:
            segment = segment.model_copy(update={"end": round(clamped_end, 3)})
        valid.append(segment)

    if not valid:
        return []

    ordered = sorted(valid, key=lambda item: (item.start, item.segment_id))
    normalized: list[SegmentAnalysis] = [ordered[0]]
    for segment in ordered[1:]:
        previous = normalized[-1]
        if segment.start < previous.end - 0.05:
            if _segment_strength(segment) > _segment_strength(previous):
                normalized[-1] = segment
            logger.info(
                "Resolved overlapping segments %s/%s at %.2f-%.2f",
                previous.segment_id,
                segment.segment_id,
                segment.start,
                previous.end,
            )
            continue
        normalized.append(segment)
    return normalized


def _validate_candidate_segments(
    segments: list[SegmentAnalysis],
    *,
    source_duration: float,
    known_segment_ids: set[int],
) -> list[SegmentAnalysis]:
    normalized = _normalize_candidate_segments(
        segments,
        source_duration=source_duration,
        known_segment_ids=known_segment_ids,
    )
    if not normalized:
        raise ClipSelectionProcessError("Clip candidate must include at least one valid segment.")
    start = normalized[0].start
    end = normalized[-1].end
    if end - start <= 0:
        raise ClipSelectionProcessError("Clip candidate duration must be positive.")
    if source_duration > 0 and end > source_duration + 0.05:
        raise ClipSelectionProcessError(
            "Clip candidate extends beyond the source video duration."
        )
    return normalized


def _options_for_duration_class(
    base: ClipSelectionOptions,
    duration_class: ClipDurationClass,
) -> ClipSelectionOptions:
    return ClipSelectionOptions(
        min_duration_seconds=base.min_duration_seconds,
        preferred_min_duration_seconds=duration_class.min_seconds,
        preferred_max_duration_seconds=duration_class.max_seconds,
        max_duration_seconds=duration_class.max_seconds,
        max_gap_seconds=base.max_gap_seconds,
        max_candidates=base.max_candidates,
        min_score=base.min_score,
        context_padding_seconds=base.context_padding_seconds,
    )


def _build_candidate(
    segments: list[SegmentAnalysis],
    transcript_segments: dict[int, TranscriptSegment],
    *,
    source_duration: float,
    known_segment_ids: set[int],
    options: ClipSelectionOptions,
    all_segments: list[SegmentAnalysis],
    duration_class: ClipDurationClass | None = None,
) -> ClipCandidate | None:
    if not segments:
        return None

    segments = _trim_group_to_max_duration(segments, options)
    segments = _expand_group_segments(
        segments,
        all_segments,
        options,
        transcript_segments,
    )
    segments = _trim_group_to_max_duration(segments, options)

    try:
        segments = _validate_candidate_segments(
            segments,
            source_duration=source_duration,
            known_segment_ids=known_segment_ids,
        )
    except ClipSelectionProcessError as exc:
        logger.warning("Candidate rejected during normalization: %s", exc.message)
        return None

    start = segments[0].start
    end = segments[-1].end
    duration = round(end - start, 3)
    hook_score = _hook_score(segments)
    payoff_score = _payoff_score(segments)
    standalone_score = _average_score(segments, "standalone_score")
    context_dependency_score = _average_score(segments, "context_dependency_score")
    primary_emotion = _dominant_emotion(segments)
    warnings: list[str] = []

    if duration < options.min_duration_seconds:
        if source_duration > 0 and end >= source_duration - 0.05 and start <= 0.05:
            warnings.append("Clip reaches source media boundary and cannot expand to 15 seconds.")
        else:
            return None
    elif duration > options.max_duration_seconds:
        return None

    if duration < options.preferred_min_duration_seconds:
        warnings.append(
            f"Clip duration {duration:.1f}s is below preferred minimum "
            f"{options.preferred_min_duration_seconds:.0f}s."
        )

    score, score_breakdown = _compute_candidate_score(
        segments,
        hook_score=hook_score,
        payoff_score=payoff_score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
        duration=duration,
        options=options,
    )
    importance = compute_importance_breakdown(
        segments,
        hook_score=hook_score,
        payoff_score=payoff_score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
        primary_emotion=primary_emotion,
    )
    importance_score = importance_total_score(importance)
    score = round((score * 0.35) + (importance_score * 0.65), 1)
    score_breakdown.update(importance_breakdown_to_score_dict(importance))
    score_breakdown["legacy_score_component"] = round(score - importance_score * 0.65, 2)
    score_breakdown["importance_total"] = importance_score

    weakness = assess_candidate_weakness(
        segments,
        hook_score=hook_score,
        payoff_score=payoff_score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
        importance=importance,
        total_score=score,
        min_score=options.min_score,
    )
    if weakness.reject:
        logger.info(
            "Rejected weak candidate %.2f-%.2f: %s",
            start,
            end,
            weakness.reason,
        )
        return None

    confidence = _compute_confidence(
        segments,
        score=score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
    )
    selection_reasons = build_selection_reasons(
        importance,
        hook_score=hook_score,
        payoff_score=payoff_score,
        primary_emotion=primary_emotion,
    )
    warnings.extend(
        build_selection_warnings(
            segments,
            hook_score=hook_score,
            context_dependency_score=context_dependency_score,
            importance=importance,
            confidence=confidence,
        )
    )
    reason = build_human_reason(
        selection_reasons,
        total_score=score,
        importance=importance,
    )

    if duration_class is not None:
        score_breakdown["duration_target_min"] = duration_class.min_seconds
        score_breakdown["duration_target_max"] = duration_class.max_seconds

    return ClipCandidate(
        clip_id=str(uuid.uuid4()),
        start=round(start, 3),
        end=round(end, 3),
        duration=duration,
        segment_ids=[segment.segment_id for segment in segments],
        transcript_text=_build_transcript_text(segments, transcript_segments),
        score=score,
        confidence=confidence,
        primary_emotion=primary_emotion,
        hook_score=hook_score,
        payoff_score=payoff_score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
        title_suggestion=_build_title_suggestion(segments, primary_emotion),
        reason=reason,
        status=ClipCandidateStatus.PROPOSED,
        warnings=warnings,
        duration_exception_reason=None,
        duration_class=duration_class.label if duration_class is not None else None,
        score_breakdown=score_breakdown,
        importance_breakdown=importance,
        selection_reasons=selection_reasons,
        visual_evidence=empty_visual_evidence(),
    )


def _candidates_overlap(first: ClipCandidate, second: ClipCandidate) -> bool:
    return first.start < second.end and second.start < first.end


def _group_strength(group: list[SegmentAnalysis]) -> float:
    return sum(_segment_strength(segment) for segment in group) / len(group)


def _rank_seed_groups(groups: list[list[SegmentAnalysis]]) -> list[list[SegmentAnalysis]]:
    return sorted(groups, key=_group_strength, reverse=True)


def _select_construction_seed_groups(
    groups: list[list[SegmentAnalysis]],
    source_duration: float,
) -> list[list[SegmentAnalysis]]:
    ranked = _rank_seed_groups(groups)
    cap = max(1, settings.clip_selection_max_seed_groups)
    selected: list[list[SegmentAnalysis]] = []
    seen_starts: set[float] = set()

    def add_group(group: list[SegmentAnalysis]) -> None:
        key = round(group[0].start, 2)
        if key in seen_starts:
            return
        seen_starts.add(key)
        selected.append(group)

    for group in ranked[:cap]:
        add_group(group)

    opening_threshold = settings.clip_selection_opening_coverage_seconds
    opening_groups = [group for group in ranked if group[0].start <= opening_threshold]
    if opening_groups:
        earliest_opening = min(opening_groups, key=lambda group: group[0].start)
        add_group(earliest_opening)

    return selected


def _duration_classes_for_selection(
    group: list[SegmentAnalysis],
    source_duration: float,
) -> list[ClipDurationClass]:
    span = group[-1].end - group[0].start
    classes = [ClipDurationClass("short", settings.clip_selection_short_min_seconds, settings.clip_selection_short_max_seconds)]
    if span >= settings.clip_selection_medium_min_seconds or source_duration >= settings.clip_selection_medium_min_seconds:
        classes.append(
            ClipDurationClass("medium", settings.clip_selection_medium_min_seconds, settings.clip_selection_medium_max_seconds)
        )
    if span >= settings.clip_selection_long_min_seconds:
        classes.append(
            ClipDurationClass("long", settings.clip_selection_long_min_seconds, settings.clip_selection_long_max_seconds)
        )
    return classes


def _candidate_overlap_ratio(first: ClipCandidate, second: ClipCandidate) -> float:
    overlap_start = max(first.start, second.start)
    overlap_end = min(first.end, second.end)
    if overlap_end <= overlap_start:
        return 0.0
    overlap = overlap_end - overlap_start
    shorter = min(first.duration, second.duration)
    return overlap / shorter if shorter > 0 else 0.0


def _duration_preference_bonus(candidate: ClipCandidate) -> float:
    preferred_max = settings.clip_selection_preferred_target_max_seconds
    preferred_min = settings.clip_selection_preferred_min_duration_seconds
    if preferred_min <= candidate.duration <= preferred_max:
        return 8.0
    if candidate.duration < preferred_min:
        return -6.0
    if candidate.duration <= preferred_max + 15.0:
        return 2.0
    return -2.0


def _quality_first_final_selection(
    candidates: list[ClipCandidate],
    *,
    max_count: int,
    min_score: float,
    source_duration: float,
) -> list[ClipCandidate]:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.duration + 0.01 >= settings.clip_selection_min_duration_seconds
        or source_duration + 0.05 < settings.clip_selection_min_duration_seconds
    ]
    eligible = [candidate for candidate in eligible if candidate.score >= min_score]
    eligible.sort(
        key=lambda candidate: (
            candidate.score + _duration_preference_bonus(candidate),
            candidate.confidence,
            -candidate.start,
        ),
        reverse=True,
    )

    selected: list[ClipCandidate] = []
    for candidate in eligible:
        if len(selected) >= max_count:
            break
        if any(_candidate_overlap_ratio(candidate, existing) >= 0.55 for existing in selected):
            if not selected or candidate.score <= selected[-1].score + 4.0:
                continue
        same_class = [
            existing
            for existing in selected
            if existing.duration_class == candidate.duration_class
            and _candidate_overlap_ratio(candidate, existing) >= 0.35
        ]
        if same_class and candidate.score <= max(existing.score for existing in same_class) + 1.5:
            continue
        selected.append(candidate)

    selected.sort(key=lambda candidate: candidate.start)
    return selected


def _duration_class_limits(duration_class: str | None) -> tuple[float, float]:
    if duration_class == "medium":
        return (
            settings.clip_selection_medium_min_seconds,
            settings.clip_selection_medium_max_seconds,
        )
    if duration_class == "long":
        return (
            settings.clip_selection_long_min_seconds,
            settings.clip_selection_long_max_seconds,
        )
    return (
        settings.clip_selection_short_min_seconds,
        settings.clip_selection_short_max_seconds,
    )


def _refine_final_candidate_boundaries(
    candidate: ClipCandidate,
    analysis_segments: list[SegmentAnalysis],
    transcript_segments: dict[int, TranscriptSegment],
    *,
    source_duration: float,
    max_gap_seconds: float,
    context_padding_seconds: float,
    visual_document=None,
) -> ClipCandidate:
    by_id = _ordered_segments_by_id(analysis_segments)
    core_segments = [
        by_id[segment_id]
        for segment_id in candidate.segment_ids
        if segment_id in by_id
    ]
    if not core_segments:
        return candidate

    _, max_duration = _duration_class_limits(candidate.duration_class)
    refinement = refine_clip_segment_boundaries(
        core_segments,
        analysis_segments,
        max_gap_seconds=max_gap_seconds,
        context_padding_seconds=context_padding_seconds,
        max_duration_seconds=max_duration,
        min_tail_seconds=settings.clip_selection_post_payoff_tail_min_seconds,
        max_tail_seconds=settings.clip_selection_post_payoff_tail_max_seconds,
        max_lead_in_seconds=settings.clip_selection_lead_in_max_seconds,
        visual_document=visual_document,
    )
    try:
        refined_segments = _validate_candidate_segments(
            refinement.segments,
            source_duration=source_duration,
            known_segment_ids=set(by_id),
        )
    except ClipSelectionProcessError:
        return candidate

    start = round(refined_segments[0].start, 3)
    end = round(refined_segments[-1].end, 3)
    duration = round(end - start, 3)
    if duration + 0.01 < settings.clip_selection_min_duration_seconds:
        return candidate

    warnings = list(candidate.warnings)
    for adjustment in refinement.adjustments:
        message = adjustment.reason
        if adjustment.direction == "end" and "Extended" not in message:
            message = (
                f"Extended end by {adjustment.seconds:.1f}s for a natural completion after the payoff."
            )
        elif adjustment.direction == "start" and "Added" not in message:
            message = f"Added {adjustment.seconds:.1f}s lead-in for clearer standalone context."
        if message not in warnings:
            warnings.append(message)

    return candidate.model_copy(
        update={
            "start": start,
            "end": end,
            "duration": duration,
            "segment_ids": [segment.segment_id for segment in refined_segments],
            "transcript_text": _build_transcript_text(refined_segments, transcript_segments),
            "warnings": warnings,
        }
    )


def _refine_final_candidates_boundaries(
    candidates: list[ClipCandidate],
    analysis_segments: list[SegmentAnalysis],
    transcript_segments: dict[int, TranscriptSegment],
    *,
    source_duration: float,
    max_gap_seconds: float,
    context_padding_seconds: float,
    visual_document=None,
) -> list[ClipCandidate]:
    return [
        _refine_final_candidate_boundaries(
            candidate,
            analysis_segments,
            transcript_segments,
            source_duration=source_duration,
            max_gap_seconds=max_gap_seconds,
            context_padding_seconds=context_padding_seconds,
            visual_document=visual_document,
        )
        for candidate in candidates
    ]


def _validate_final_candidates(
    candidates: list[ClipCandidate],
    *,
    source_duration: float,
) -> list[ClipCandidate]:
    validated: list[ClipCandidate] = []
    for candidate in candidates:
        if candidate.duration + 0.01 < settings.clip_selection_min_duration_seconds:
            if source_duration + 0.05 >= settings.clip_selection_min_duration_seconds:
                logger.warning(
                    "Rejected final candidate %.2f-%.2f (%.2fs) below minimum duration.",
                    candidate.start,
                    candidate.end,
                    candidate.duration,
                )
                continue
        validated.append(candidate)
    return validated


def _sync_analysis_clip_flags(project_id: str, final_candidates: list[ClipCandidate]) -> None:
    selected_segment_ids = {
        segment_id for candidate in final_candidates for segment_id in candidate.segment_ids
    }
    analysis = load_project_analysis(project_id)
    updated_segments = [
        segment.model_copy(
            update={
                "clip_candidate": segment.clip_candidate or segment.segment_id in selected_segment_ids,
            }
        )
        for segment in analysis.segments
    ]
    updated_document = analysis.model_copy(
        update={
            "segments": updated_segments,
            "clip_candidate_count": sum(1 for segment in updated_segments if segment.clip_candidate),
        }
    )
    from app.services.timeline_analysis import _write_analysis_atomically

    _write_analysis_atomically(project_id, updated_document)


def is_clip_candidates_document_current(document: ClipCandidatesDocument) -> bool:
    return document.selection_pipeline_version == settings.clip_selection_pipeline_version


def invalidate_stale_clip_candidates(project_id: str) -> bool:
    output_path = get_clip_candidates_output_path(project_id)
    if not output_path.exists():
        return False
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        document = ClipCandidatesDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return False
    if is_clip_candidates_document_current(document):
        return False
    cleanup_clip_candidates_output(project_id)
    project = load_project(project_id)
    project.clip_selection_status = ProcessingStatus.PENDING
    project.clip_candidates_path = None
    project.clip_candidate_count = None
    project.append_log(
        "Stale clip candidates invalidated due to selection pipeline version change.",
    )
    save_project(project)
    return True


def _deduplicate_candidates(candidates: list[ClipCandidate]) -> list[ClipCandidate]:
    logger.info("Clip candidates before overlap resolution: %s", len(candidates))
    for candidate in candidates:
        logger.info(
            "Candidate start=%.2f end=%.2f duration=%.2f score=%.1f",
            candidate.start,
            candidate.end,
            candidate.duration,
            candidate.score,
        )

    ranked = sorted(
        candidates,
        key=lambda candidate: (candidate.score, candidate.confidence, -candidate.start),
        reverse=True,
    )
    kept: list[ClipCandidate] = []

    for candidate in ranked:
        overlapping = [existing for existing in kept if _candidates_overlap(candidate, existing)]
        if not overlapping:
            kept.append(candidate)
            continue

        existing = overlapping[0]
        margin = settings.clip_selection_narrative_arc_score_margin

        if (
            candidate.start >= existing.start
            and candidate.end <= existing.end
            and candidate.score <= existing.score + margin
        ):
            logger.info(
                "Dropped payoff-only subclip %.2f-%.2f in favor of narrative arc %.2f-%.2f",
                candidate.start,
                candidate.end,
                existing.start,
                existing.end,
            )
            continue

        if (
            existing.start >= candidate.start
            and existing.end <= candidate.end
            and candidate.score + margin >= existing.score
        ):
            kept.remove(existing)
            kept.append(candidate)
            logger.info(
                "Kept broader narrative arc %.2f-%.2f over subclip %.2f-%.2f",
                candidate.start,
                candidate.end,
                existing.start,
                existing.end,
            )
            continue

        if candidate.score > existing.score + margin:
            kept.remove(existing)
            kept.append(candidate)
            logger.info(
                "Resolved overlap by keeping higher-score candidate %.2f-%.2f over %.2f-%.2f",
                candidate.start,
                candidate.end,
                existing.start,
                existing.end,
            )
            continue

        if candidate.start >= existing.start and candidate.end <= existing.end:
            logger.info("Dropped near-duplicate candidate inside existing range")
            continue

        if existing.start <= candidate.start and existing.end >= candidate.end:
            logger.info("Dropped lower-score candidate contained by existing range")
            continue

        logger.info(
            "Resolved overlap by keeping existing candidate %.2f-%.2f over %.2f-%.2f",
            existing.start,
            existing.end,
            candidate.start,
            candidate.end,
        )

    kept.sort(key=lambda candidate: candidate.start)
    logger.info("Clip candidates after overlap resolution: %s", len(kept))
    return kept


def _validate_document(document: ClipCandidatesDocument) -> ClipCandidatesDocument:
    try:
        return ClipCandidatesDocument.model_validate(document.model_dump(mode="json"))
    except ValidationError as exc:
        raise ClipSelectionProcessError(
            _sanitize_error_message(f"Invalid clip candidates document: {exc}")
        ) from exc


def _write_clip_candidates_atomically(
    project_id: str,
    document: ClipCandidatesDocument,
) -> str:
    output_dir = get_clip_candidates_output_dir(project_id)
    output_path = get_clip_candidates_output_path(project_id)
    partial_path = output_dir / f"{settings.clip_candidates_output_filename}.part"

    partial_path.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    partial_path.replace(output_path)
    return get_relative_clip_candidates_path(project_id)


def select_project_clips(
    project_id: str,
    *,
    min_duration_seconds: float | None = None,
    max_duration_seconds: float | None = None,
    max_gap_seconds: float | None = None,
    max_candidates: int | None = None,
    min_score: float | None = None,
) -> ClipCandidatesDocument:
    selection_started = time.perf_counter()
    log_stage_event("clip_selection", "start", project_id=project_id)
    options = resolve_selection_options(
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        max_gap_seconds=max_gap_seconds,
        max_candidates=max_candidates,
        min_score=min_score,
    )
    transcript, analysis = _require_completed_inputs(project_id)
    source_duration = _source_duration(transcript, analysis, project_id)
    transcript_segments = {segment.id: segment for segment in transcript.segments}
    known_segment_ids = set(transcript_segments)
    visual_document = (
        try_load_project_visual_analysis(project_id)
        if settings.visual_analysis_enabled and should_apply_visual_boundaries()
        else None
    )
    visual_scoring_document = (
        try_load_project_visual_analysis(project_id)
        if settings.visual_analysis_enabled
        and settings.visual_analysis_ranking_mode.lower() in {"conservative", "shadow"}
        else None
    )

    try:
        cleanup_clip_candidates_output(project_id)
        seed_groups = _group_seed_segments(analysis.segments, options.max_gap_seconds)
        groups = _select_construction_seed_groups(seed_groups, source_duration)
        raw_candidates: list[ClipCandidate] = []

        construction_started = time.perf_counter()
        for group in groups:
            for duration_class in _duration_classes_for_selection(group, source_duration):
                class_options = _options_for_duration_class(options, duration_class)
                candidate = _build_candidate(
                    group,
                    transcript_segments,
                    source_duration=source_duration,
                    known_segment_ids=known_segment_ids,
                    options=class_options,
                    all_segments=analysis.segments,
                    duration_class=duration_class,
                )
                if candidate is not None:
                    raw_candidates.append(candidate)
                if len(raw_candidates) >= settings.clip_selection_max_candidates_before_ranking:
                    break
            if len(raw_candidates) >= settings.clip_selection_max_candidates_before_ranking:
                break
        log_stage_event(
            "constructing_candidates",
            "complete",
            project_id=project_id,
            candidates=len(raw_candidates),
            elapsed=f"{time.perf_counter() - construction_started:.3f}s",
        )

        raw_candidates = apply_visual_scoring(
            raw_candidates,
            visual_scoring_document,
            quality_threshold=max(
                options.min_score,
                settings.clip_selection_quality_threshold,
            ),
        )

        ranking_started = time.perf_counter()
        deduplicated = _deduplicate_candidates(raw_candidates)
        quality_threshold = max(
            options.min_score,
            settings.clip_selection_quality_threshold,
        )
        final_candidates, rejected_candidates = global_importance_selection(
            deduplicated,
            max_count=options.max_candidates,
            quality_threshold=quality_threshold,
            source_duration=source_duration,
        )
        final_candidates = _validate_final_candidates(
            final_candidates,
            source_duration=source_duration,
        )
        final_candidates = _refine_final_candidates_boundaries(
            final_candidates,
            analysis.segments,
            transcript_segments,
            source_duration=source_duration,
            max_gap_seconds=options.max_gap_seconds,
            context_padding_seconds=options.context_padding_seconds,
            visual_document=visual_document,
        )
        log_stage_event(
            "ranking_candidates",
            "complete",
            project_id=project_id,
            candidates=len(final_candidates),
            elapsed=f"{time.perf_counter() - ranking_started:.3f}s",
        )

        persistence_started = time.perf_counter()
        document = ClipCandidatesDocument(
            project_id=project_id,
            candidate_count=len(final_candidates),
            min_duration_seconds=options.min_duration_seconds,
            max_duration_seconds=options.max_duration_seconds,
            max_gap_seconds=options.max_gap_seconds,
            max_candidates=options.max_candidates,
            source_duration_seconds=source_duration,
            candidates=final_candidates,
            rejected_candidates=rejected_candidates[:20],
            quality_threshold=quality_threshold,
            selection_pipeline_version=settings.clip_selection_pipeline_version,
            analysis_pipeline_version=settings.analysis_pipeline_version,
            visual_analysis_pipeline_version=(
                visual_scoring_document.pipeline_version
                if visual_scoring_document is not None
                else None
            ),
        )
        document = _validate_document(document)
        _write_clip_candidates_atomically(project_id, document)
        log_stage_event(
            "saving_results",
            "complete",
            project_id=project_id,
            elapsed=f"{time.perf_counter() - persistence_started:.3f}s",
        )
        log_timing_summary(
            project_id=project_id,
            pipeline="clip_selection",
            total_seconds=time.perf_counter() - selection_started,
            candidates=document.candidate_count,
            raw_candidates=len(raw_candidates),
            deduplicated=len(deduplicated),
        )
        return document
    except (
        ClipSelectionTranscriptRequiredError,
        ClipSelectionAnalysisRequiredError,
        InvalidAnalysisForSelectionError,
        ClipSelectionProcessError,
    ):
        cleanup_clip_candidates_output(project_id)
        raise
    except Exception as exc:
        cleanup_clip_candidates_output(project_id)
        raise ClipSelectionProcessError(
            _sanitize_error_message(f"Clip selection failed: {exc}")
        ) from exc


def load_clip_candidate(project_id: str, candidate_id: str) -> ClipCandidate:
    document = load_project_clip_candidates(project_id)
    for candidate in document.candidates:
        if candidate.clip_id == candidate_id:
            return candidate
    raise ClipCandidatesNotFoundError(f"Clip candidate '{candidate_id}' was not found.")


def load_project_clip_candidates(project_id: str) -> ClipCandidatesDocument:
    load_project(project_id)

    output_path = get_clip_candidates_output_path(project_id)
    if not output_path.exists() or not output_path.is_file():
        raise ClipCandidatesNotFoundError(
            "Clip candidates not found. Run clip selection before loading results."
        )

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        document = ClipCandidatesDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ClipSelectionProcessError("Clip candidates file is corrupted.") from exc

    if not is_clip_candidates_document_current(document):
        raise ClipCandidatesNotFoundError(
            "Clip candidates are outdated for the current selection pipeline. Run Select Clips again."
        )
    return document
