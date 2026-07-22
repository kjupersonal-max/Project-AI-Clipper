from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.config import settings
from app.models.project import (
    AnalysisDocument,
    ClipCandidate,
    ClipCandidateStatus,
    ClipCandidatesDocument,
    SegmentAnalysis,
    TranscriptDocument,
    TranscriptSegment,
)
from app.services.project_store import (
    get_clip_candidates_output_dir,
    get_clip_candidates_output_path,
    get_relative_clip_candidates_path,
    load_project,
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
class ClipSelectionOptions:
    min_duration_seconds: float
    max_duration_seconds: float
    max_gap_seconds: float
    max_candidates: int
    min_score: float


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
    resolved_max = max_duration_seconds or settings.clip_selection_max_duration_seconds
    resolved_gap = max_gap_seconds or settings.clip_selection_max_gap_seconds
    resolved_max_candidates = max_candidates or settings.clip_selection_max_candidates
    resolved_min_score = min_score if min_score is not None else settings.clip_selection_min_score

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
    if not 0.0 <= resolved_min_score <= 100.0:
        raise ClipSelectionProcessError("Minimum score must be between 0 and 100.")

    return ClipSelectionOptions(
        min_duration_seconds=resolved_min,
        max_duration_seconds=resolved_max,
        max_gap_seconds=resolved_gap,
        max_candidates=resolved_max_candidates,
        min_score=resolved_min_score,
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
        transcript = load_project_transcript(project_id)
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
) -> list[SegmentAnalysis]:
    by_id = _ordered_segments_by_id(all_segments)
    min_id = min(segment.segment_id for segment in group)
    max_id = max(segment.segment_id for segment in group)
    selected_ids = {segment.segment_id for segment in group}
    selected = [by_id[segment_id] for segment_id in sorted(selected_ids)]

    def current_duration() -> float:
        return selected[-1].end - selected[0].start

    while current_duration() < options.min_duration_seconds:
        expanded = False
        previous_id = min_id - 1
        next_id = max_id + 1

        previous_segment = by_id.get(previous_id)
        next_segment = by_id.get(next_id)
        candidates: list[tuple[float, SegmentAnalysis, str]] = []

        if previous_segment is not None:
            gap = selected[0].start - previous_segment.end
            if gap <= options.max_gap_seconds:
                projected = selected[-1].end - previous_segment.start
                if projected <= options.max_duration_seconds:
                    candidates.append((_segment_strength(previous_segment), previous_segment, "prev"))

        if next_segment is not None:
            gap = next_segment.start - selected[-1].end
            if gap <= options.max_gap_seconds:
                projected = next_segment.end - selected[0].start
                if projected <= options.max_duration_seconds:
                    candidates.append((_segment_strength(next_segment), next_segment, "next"))

        if not candidates:
            break

        _, chosen, direction = max(candidates, key=lambda item: item[0])
        if direction == "prev":
            selected.insert(0, chosen)
            min_id = chosen.segment_id
        else:
            selected.append(chosen)
            max_id = chosen.segment_id
        selected_ids.add(chosen.segment_id)
        expanded = True

        if not expanded:
            break

    return selected


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
) -> float:
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

    score = (
        hook_score * 4.5
        + payoff_score * 3.5
        + standalone_score * 4.0
        + peak_engagement * 2.5
        + average_engagement * 2.0
        - context_dependency_score * 3.0
    )
    normalized = (score / 70.0) * 100.0
    return round(_clamp(normalized, 0.0, 100.0), 1)


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


def _validate_candidate_segments(
    segments: list[SegmentAnalysis],
    *,
    source_duration: float,
    known_segment_ids: set[int],
) -> None:
    if not segments:
        raise ClipSelectionProcessError("Clip candidate must include at least one segment.")

    previous_end: float | None = None
    for segment in segments:
        if segment.segment_id not in known_segment_ids:
            raise ClipSelectionProcessError(
                f"Clip candidate references unknown segment ID {segment.segment_id}."
            )
        if segment.end <= segment.start:
            raise ClipSelectionProcessError(
                f"Invalid segment timing for segment {segment.segment_id}."
            )
        if previous_end is not None and segment.start < previous_end:
            raise ClipSelectionProcessError(
                "Clip candidate segments overlap or are out of order."
            )
        previous_end = segment.end

    start = segments[0].start
    end = segments[-1].end
    duration = end - start
    if duration <= 0:
        raise ClipSelectionProcessError("Clip candidate duration must be positive.")
    if source_duration > 0 and end > source_duration + 0.05:
        raise ClipSelectionProcessError(
            "Clip candidate extends beyond the source video duration."
        )


def _build_candidate(
    segments: list[SegmentAnalysis],
    transcript_segments: dict[int, TranscriptSegment],
    *,
    source_duration: float,
    known_segment_ids: set[int],
    options: ClipSelectionOptions,
    all_segments: list[SegmentAnalysis],
) -> ClipCandidate | None:
    if not segments:
        return None

    segments = _trim_group_to_max_duration(segments, options)
    segments = _expand_group_segments(segments, all_segments, options)
    segments = _trim_group_to_max_duration(segments, options)

    _validate_candidate_segments(
        segments,
        source_duration=source_duration,
        known_segment_ids=known_segment_ids,
    )

    start = segments[0].start
    end = segments[-1].end
    duration = round(end - start, 3)
    if duration < options.min_duration_seconds or duration > options.max_duration_seconds:
        return None

    hook_score = _hook_score(segments)
    payoff_score = _payoff_score(segments)
    standalone_score = _average_score(segments, "standalone_score")
    context_dependency_score = _average_score(segments, "context_dependency_score")
    primary_emotion = _dominant_emotion(segments)
    score = _compute_candidate_score(
        segments,
        hook_score=hook_score,
        payoff_score=payoff_score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
    )
    if score < options.min_score:
        return None

    confidence = _compute_confidence(
        segments,
        score=score,
        standalone_score=standalone_score,
        context_dependency_score=context_dependency_score,
    )

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
        reason=_build_reason(
            segments,
            hook_score=hook_score,
            payoff_score=payoff_score,
            standalone_score=standalone_score,
            context_dependency_score=context_dependency_score,
            primary_emotion=primary_emotion,
        ),
        status=ClipCandidateStatus.PROPOSED,
    )


def _candidates_overlap(first: ClipCandidate, second: ClipCandidate) -> bool:
    return first.start < second.end and second.start < first.end


def _deduplicate_candidates(candidates: list[ClipCandidate]) -> list[ClipCandidate]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (candidate.score, candidate.confidence, -candidate.start),
        reverse=True,
    )
    kept: list[ClipCandidate] = []

    for candidate in ranked:
        if any(_candidates_overlap(candidate, existing) for existing in kept):
            continue
        kept.append(candidate)

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

    try:
        groups = _group_seed_segments(analysis.segments, options.max_gap_seconds)
        raw_candidates: list[ClipCandidate] = []

        for group in groups:
            candidate = _build_candidate(
                group,
                transcript_segments,
                source_duration=source_duration,
                known_segment_ids=known_segment_ids,
                options=options,
                all_segments=analysis.segments,
            )
            if candidate is not None:
                raw_candidates.append(candidate)

        deduplicated = _deduplicate_candidates(raw_candidates)
        deduplicated.sort(
            key=lambda candidate: (candidate.score, candidate.confidence, -candidate.start),
            reverse=True,
        )
        final_candidates = deduplicated[: options.max_candidates]

        document = ClipCandidatesDocument(
            project_id=project_id,
            candidate_count=len(final_candidates),
            min_duration_seconds=options.min_duration_seconds,
            max_duration_seconds=options.max_duration_seconds,
            max_gap_seconds=options.max_gap_seconds,
            max_candidates=options.max_candidates,
            source_duration_seconds=source_duration,
            candidates=final_candidates,
        )
        document = _validate_document(document)
        _write_clip_candidates_atomically(project_id, document)
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


def load_project_clip_candidates(project_id: str) -> ClipCandidatesDocument:
    load_project(project_id)

    output_path = get_clip_candidates_output_path(project_id)
    if not output_path.exists() or not output_path.is_file():
        raise ClipCandidatesNotFoundError(
            "Clip candidates not found. Run clip selection before loading results."
        )

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        return ClipCandidatesDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ClipSelectionProcessError("Clip candidates file is corrupted.") from exc
