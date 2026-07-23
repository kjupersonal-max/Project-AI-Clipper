from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.project import (
    ApplyRetranscribeRangeRequest,
    CaptionSegment,
    CaptionStyle,
    CaptionWord,
    ClipCaptionsDocument,
    ClipCaptionsResponse,
    DeleteCaptionsResponse,
    RetranscribeRangePreviewResponse,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
    TranscriptionQualityResponse,
    UpdateCaptionSegmentRequest,
    utc_now_iso,
)
from app.services.caption_editing import (
    delete_caption_word,
    find_manual_edits_in_range,
    insert_caption_segment,
    insert_caption_word,
    merge_caption_segments,
    nudge_segment_timing,
    segment_has_manual_edits,
    split_caption_segment,
)
from app.services.clip_transcription import (
    ClipTranscriptionResult,
    transcribe_clip_range,
    transcript_segments_to_caption_segments,
)
from dataclasses import dataclass

from app.services.clip_export import ClipExportNotFoundError, locate_exported_clip
from app.services.clip_retranscription import load_or_retranscribe_clip_quality_transcript
from app.services.clip_selection import (
    ClipCandidatesNotFoundError,
    load_clip_candidate,
    load_project_clip_candidates,
)
from app.services.project_store import get_clip_captions_path, load_project
from app.services.transcript_store import load_workflow_transcript
from app.services.transcription import TranscriptNotFoundError


from app.services.caption_validation import (
    ClipCaptionsValidationError,
    round_caption_time,
    validate_caption_segments,
)


class ClipCaptionsNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipCaptionsGenerationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class CaptionTarget:
    target_id: str
    start_time: float
    end_time: float
    duration: float
    candidate_id: str | None
    from_export: bool


def resolve_caption_target(project_id: str, target_id: str) -> CaptionTarget:
    try:
        record, _clip_path = locate_exported_clip(project_id, target_id)
        return CaptionTarget(
            target_id=record.clip_id,
            start_time=record.start_time,
            end_time=record.end_time,
            duration=record.duration,
            candidate_id=record.candidate_id,
            from_export=True,
        )
    except ClipExportNotFoundError:
        pass

    try:
        candidate = load_clip_candidate(project_id, target_id)
    except ClipCandidatesNotFoundError as exc:
        raise ClipExportNotFoundError(
            f"Clip or candidate '{target_id}' was not found. Export the clip or run Select Clips first."
        ) from exc

    return CaptionTarget(
        target_id=candidate.clip_id,
        start_time=candidate.start,
        end_time=candidate.end,
        duration=candidate.duration,
        candidate_id=candidate.clip_id,
        from_export=False,
    )


def _caption_storage_id(target: CaptionTarget) -> str:
    return target.candidate_id or target.target_id


def _load_captions_for_target(project_id: str, target: CaptionTarget) -> ClipCaptionsDocument:
    return _load_captions_document(project_id, _caption_storage_id(target))


def _source_duration_seconds(project_id: str) -> float:
    project = load_project(project_id)
    if project.video_metadata and project.video_metadata.duration_seconds:
        return project.video_metadata.duration_seconds
    return 0.0


def _validate_caption_target_duration(target: CaptionTarget, project_id: str) -> None:
    source_duration = _source_duration_seconds(project_id)
    if target.duration + 0.01 < settings.clip_export_min_duration_seconds:
        if source_duration + 0.05 >= settings.clip_export_min_duration_seconds:
            raise ClipCaptionsGenerationError(
                f"Clip duration ({target.duration:.2f}s) is below the minimum "
                f"{settings.clip_export_min_duration_seconds:.1f}s required for caption generation."
            )


def _round_time(value: float) -> float:
    return round_caption_time(value)


def _segments_overlap(
    segment_start: float,
    segment_end: float,
    clip_start: float,
    clip_end: float,
) -> bool:
    return segment_end > clip_start and segment_start < clip_end


def _clamp_to_clip(time: float, clip_start: float, clip_end: float) -> float:
    return max(clip_start, min(time, clip_end))


def _to_clip_relative(time: float, clip_start: float) -> float:
    return _round_time(time - clip_start)


def _convert_word_to_clip_relative(
    word: TranscriptWord,
    clip_start: float,
    clip_end: float,
) -> CaptionWord | None:
    if not _segments_overlap(word.start, word.end, clip_start, clip_end):
        return None

    relative_start = _to_clip_relative(_clamp_to_clip(word.start, clip_start, clip_end), clip_start)
    relative_end = _to_clip_relative(_clamp_to_clip(word.end, clip_start, clip_end), clip_start)
    if relative_end <= relative_start:
        return None

    return CaptionWord(word=word.word, start=relative_start, end=relative_end)


def _caption_from_transcript_segment(
    segment: TranscriptSegment,
    clip_start: float,
    clip_end: float,
    sequence: int,
) -> CaptionSegment | None:
    if not _segments_overlap(segment.start, segment.end, clip_start, clip_end):
        return None

    now = utc_now_iso()
    relative_words: list[CaptionWord] = []

    for word in segment.words:
        converted = _convert_word_to_clip_relative(word, clip_start, clip_end)
        if converted is not None:
            relative_words.append(converted)

    if relative_words:
        text = " ".join(relative_word.word for relative_word in relative_words).strip()
        start = relative_words[0].start
        end = relative_words[-1].end
    else:
        text = segment.text.strip()
        start = _to_clip_relative(_clamp_to_clip(segment.start, clip_start, clip_end), clip_start)
        end = _to_clip_relative(_clamp_to_clip(segment.end, clip_start, clip_end), clip_start)

    if end <= start:
        return None

    return CaptionSegment(
        id=str(uuid.uuid4()),
        text=text,
        start=start,
        end=end,
        words=relative_words,
        sequence=sequence,
        created_at=now,
        updated_at=now,
    )


def extract_caption_segments_from_transcript(
    transcript: TranscriptDocument,
    clip_start: float,
    clip_end: float,
) -> list[CaptionSegment]:
    segments: list[CaptionSegment] = []
    sequence = 0

    for transcript_segment in transcript.segments:
        caption_segment = _caption_from_transcript_segment(
            transcript_segment,
            clip_start,
            clip_end,
            sequence,
        )
        if caption_segment is not None:
            segments.append(caption_segment)
            sequence += 1

    return segments


def _validate_caption_segments(segments: list[CaptionSegment], clip_duration: float) -> None:
    validate_caption_segments(segments, clip_duration)


def _default_caption_style() -> CaptionStyle:
    from app.services.caption_presets import get_default_caption_style

    return get_default_caption_style()


def _resolve_caption_style(document: ClipCaptionsDocument) -> CaptionStyle:
    if document.style is None:
        return _default_caption_style()
    return document.style


def _document_to_response(document: ClipCaptionsDocument) -> ClipCaptionsResponse:
    return ClipCaptionsResponse(
        project_id=document.project_id,
        clip_id=document.clip_id,
        source_start_time=document.source_start_time,
        source_end_time=document.source_end_time,
        duration=document.duration,
        candidate_id=document.candidate_id,
        segments=document.segments,
        style=_resolve_caption_style(document),
        created_at=document.created_at,
        updated_at=document.updated_at,
        transcription_quality_mode=document.transcription_quality_mode,
        transcription_quality_rating=document.transcription_quality_rating,
        transcription_warnings=document.transcription_warnings,
        vocabulary_hints=document.vocabulary_hints,
    )


def _write_captions_document(document: ClipCaptionsDocument) -> None:
    captions_path = get_clip_captions_path(document.project_id, document.clip_id)
    captions_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = captions_path.with_suffix(".json.part")
    temp_path.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    temp_path.replace(captions_path)


def _load_captions_document(project_id: str, clip_id: str) -> ClipCaptionsDocument:
    captions_path = get_clip_captions_path(project_id, clip_id)
    if not captions_path.exists():
        raise ClipCaptionsNotFoundError("Captions not found for this clip.")

    try:
        payload = json.loads(captions_path.read_text(encoding="utf-8"))
        return ClipCaptionsDocument.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ClipCaptionsValidationError("Caption data is corrupted.") from exc


def delete_clip_captions(project_id: str, clip_id: str) -> bool:
    captions_path = get_clip_captions_path(project_id, clip_id)
    if captions_path.exists() and captions_path.is_file():
        captions_path.unlink()
        return True
    return False


def get_clip_captions(project_id: str, clip_id: str) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    document = _load_captions_for_target(project_id, target)
    return _document_to_response(document)


def generate_clip_captions(project_id: str, clip_id: str) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    _validate_caption_target_duration(target, project_id)

    clip_transcript = load_or_retranscribe_clip_quality_transcript(
        project_id=project_id,
        clip_id=target.target_id,
        clip_start=target.start_time,
        clip_end=target.end_time,
        candidate_id=target.candidate_id,
    )
    if not clip_transcript.segments:
        raise ClipCaptionsGenerationError(
            "High-quality clip transcription produced no segments for this range."
        )

    segments = extract_caption_segments_from_transcript(
        clip_transcript,
        target.start_time,
        target.end_time,
    )
    if not segments:
        raise ClipCaptionsGenerationError(
            "No transcript content overlaps this clip's time range."
        )

    _validate_caption_segments(segments, target.duration)

    now = utc_now_iso()
    storage_id = _caption_storage_id(target)
    document = ClipCaptionsDocument(
        project_id=project_id,
        clip_id=storage_id,
        source_start_time=target.start_time,
        source_end_time=target.end_time,
        duration=target.duration,
        candidate_id=target.candidate_id,
        segments=segments,
        style=_default_caption_style(),
        created_at=now,
        updated_at=now,
        transcription_quality_mode=clip_transcript.quality_mode,
        transcription_quality_rating=clip_transcript.quality_rating,
        transcription_warnings=[
            *clip_transcript.quality_warnings,
            "Final captions generated from clip-quality retranscription.",
        ],
        vocabulary_hints=clip_transcript.vocabulary_hints,
    )
    _write_captions_document(document)
    return _document_to_response(document)


def update_clip_captions(
    project_id: str,
    clip_id: str,
    segment_updates: list[UpdateCaptionSegmentRequest],
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)

    existing_by_id = {segment.id: segment for segment in existing.segments}
    updated_segments: list[CaptionSegment] = []
    now = utc_now_iso()

    for update in sorted(segment_updates, key=lambda item: item.sequence):
        if update.id not in existing_by_id:
            raise ClipCaptionsValidationError(f"Unknown caption segment ID: {update.id}.")

        previous = existing_by_id[update.id]
        updated_segments.append(
            CaptionSegment(
                id=update.id,
                text=update.text,
                start=_round_time(update.start),
                end=_round_time(update.end),
                words=[
                    CaptionWord(
                        word=word.word,
                        start=_round_time(word.start),
                        end=_round_time(word.end),
                    )
                    for word in update.words
                ],
                sequence=update.sequence,
                created_at=previous.created_at,
                updated_at=now,
                manually_edited=previous.manually_edited
                or previous.text != update.text
                or previous.start != update.start
                or previous.end != update.end,
                original_transcription_text=previous.original_transcription_text or previous.text,
            )
        )

    _validate_caption_segments(updated_segments, target.duration)

    document = existing.model_copy(
        update={
            "segments": updated_segments,
            "updated_at": now,
        }
    )
    _write_captions_document(document)
    return _document_to_response(document)


def reset_clip_captions(project_id: str, clip_id: str) -> DeleteCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    storage_id = _caption_storage_id(target)

    deleted = delete_clip_captions(project_id, storage_id)
    if not deleted:
        raise ClipCaptionsNotFoundError("Captions not found for this clip.")

    return DeleteCaptionsResponse(
        project_id=project_id,
        clip_id=clip_id,
        message="Captions deleted successfully.",
    )


def update_clip_caption_style(
    project_id: str,
    clip_id: str,
    style: CaptionStyle,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)

    document = existing.model_copy(
        update={
            "style": style,
            "updated_at": utc_now_iso(),
        }
    )
    _write_captions_document(document)
    return _document_to_response(document)


def reset_clip_caption_style(project_id: str, clip_id: str) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)

    document = existing.model_copy(
        update={
            "style": _default_caption_style(),
            "updated_at": utc_now_iso(),
        }
    )
    _write_captions_document(document)
    return _document_to_response(document)


def _source_range_from_clip_relative(
    range_start: float,
    range_end: float,
    source_start: float,
) -> tuple[float, float]:
    return source_start + range_start, source_start + range_end


def preview_retranscribe_range(
    project_id: str,
    clip_id: str,
    *,
    range_start: float,
    range_end: float,
    quality_mode: str | None = None,
    vocabulary_hints: str | None = None,
) -> RetranscribeRangePreviewResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    if range_end <= range_start:
        raise ClipCaptionsValidationError("Range end time must be after start time.")
    if range_end > target.duration + 0.001 or range_start < 0:
        raise ClipCaptionsValidationError("Range must remain inside clip duration.")

    existing = _load_captions_document(project_id, clip_id)
    manual_warnings = find_manual_edits_in_range(existing.segments, range_start, range_end)

    source_start, source_end = _source_range_from_clip_relative(
        range_start,
        range_end,
        target.start_time,
    )
    result = transcribe_clip_range(
        project_id=project_id,
        clip_start=source_start,
        clip_end=source_end,
        quality_mode=quality_mode,
        vocabulary_hints=vocabulary_hints or existing.vocabulary_hints,
    )
    preview_segments = transcript_segments_to_caption_segments(
        result.segments,
        clip_duration=target.duration,
    )
    for index, segment in enumerate(preview_segments):
        segment.start = _round_time(segment.start + range_start)
        segment.end = _round_time(segment.end + range_start)
        for word in segment.words:
            word.start = _round_time(word.start + range_start)
            word.end = _round_time(word.end + range_start)
        segment.sequence = index

    return RetranscribeRangePreviewResponse(
        project_id=project_id,
        clip_id=clip_id,
        start_time=range_start,
        end_time=range_end,
        preview_segments=preview_segments,
        quality_rating=result.quality_rating,
        warnings=result.warnings,
        manual_edit_warnings=[warning.message for warning in manual_warnings],
    )


def apply_retranscribe_range(
    project_id: str,
    clip_id: str,
    request: ApplyRetranscribeRangeRequest,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)

    if request.end_time <= request.start_time:
        raise ClipCaptionsValidationError("Range end time must be after start time.")

    manual_warnings = find_manual_edits_in_range(
        existing.segments,
        request.start_time,
        request.end_time,
    )
    if manual_warnings and request.mode == "cancel":
        raise ClipCaptionsValidationError("Retranscription cancelled due to manual edits.")

    replacement_segments = [
        CaptionSegment(
            id=item.id,
            text=item.text,
            start=_round_time(item.start),
            end=_round_time(item.end),
            words=[
                CaptionWord(
                    word=word.word,
                    start=_round_time(word.start),
                    end=_round_time(word.end),
                )
                for word in item.words
            ],
            sequence=item.sequence,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        for item in request.preview_segments
    ]
    _validate_caption_segments(replacement_segments, target.duration)

    preserved = [
        segment
        for segment in existing.segments
        if segment.end <= request.start_time or segment.start >= request.end_time
    ]
    merged = sorted([*preserved, *replacement_segments], key=lambda item: item.start)

    for index, segment in enumerate(merged):
        segment.sequence = index

    _validate_caption_segments(merged, target.duration)
    document = existing.model_copy(
        update={
            "segments": merged,
            "updated_at": utc_now_iso(),
        }
    )
    _write_captions_document(document)
    return _document_to_response(document)


def get_transcription_quality(project_id: str, clip_id: str) -> TranscriptionQualityResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    document = _load_captions_for_target(project_id, target)
    manual_edit_count = sum(1 for segment in document.segments if segment_has_manual_edits(segment))
    return TranscriptionQualityResponse(
        project_id=project_id,
        clip_id=clip_id,
        quality_mode=document.transcription_quality_mode,
        quality_rating=document.transcription_quality_rating,
        warnings=document.transcription_warnings,
        manual_edit_count=manual_edit_count,
    )


def update_vocabulary_hints(
    project_id: str,
    clip_id: str,
    vocabulary_hints: str | None,
) -> ClipCaptionsResponse:
    from app.services.transcription_config import sanitize_vocabulary_hints

    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    document = existing.model_copy(
        update={
            "vocabulary_hints": sanitize_vocabulary_hints(vocabulary_hints),
            "updated_at": utc_now_iso(),
        }
    )
    _write_captions_document(document)
    return _document_to_response(document)


def manual_insert_word(
    project_id: str,
    clip_id: str,
    *,
    segment_id: str,
    word: str,
    start: float,
    end: float,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    updated = insert_caption_word(
        existing.segments,
        segment_id=segment_id,
        word=word,
        start=start,
        end=end,
        clip_duration=target.duration,
    )
    document = existing.model_copy(update={"segments": updated, "updated_at": utc_now_iso()})
    _write_captions_document(document)
    return _document_to_response(document)


def manual_insert_segment(
    project_id: str,
    clip_id: str,
    *,
    text: str,
    start: float,
    end: float,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    updated = insert_caption_segment(
        existing.segments,
        text=text,
        start=start,
        end=end,
        clip_duration=target.duration,
    )
    document = existing.model_copy(update={"segments": updated, "updated_at": utc_now_iso()})
    _write_captions_document(document)
    return _document_to_response(document)


def manual_split_segment(
    project_id: str,
    clip_id: str,
    *,
    segment_id: str,
    split_time: float,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    updated = split_caption_segment(
        existing.segments,
        segment_id=segment_id,
        split_time=split_time,
        clip_duration=target.duration,
    )
    document = existing.model_copy(update={"segments": updated, "updated_at": utc_now_iso()})
    _write_captions_document(document)
    return _document_to_response(document)


def manual_merge_segments(
    project_id: str,
    clip_id: str,
    *,
    first_segment_id: str,
    second_segment_id: str,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    updated = merge_caption_segments(
        existing.segments,
        first_segment_id=first_segment_id,
        second_segment_id=second_segment_id,
        clip_duration=target.duration,
    )
    document = existing.model_copy(update={"segments": updated, "updated_at": utc_now_iso()})
    _write_captions_document(document)
    return _document_to_response(document)


def manual_nudge_timing(
    project_id: str,
    clip_id: str,
    *,
    segment_id: str,
    delta_seconds: float,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    updated = nudge_segment_timing(
        existing.segments,
        segment_id=segment_id,
        delta_seconds=delta_seconds,
        clip_duration=target.duration,
    )
    document = existing.model_copy(update={"segments": updated, "updated_at": utc_now_iso()})
    _write_captions_document(document)
    return _document_to_response(document)


def manual_delete_word(
    project_id: str,
    clip_id: str,
    *,
    segment_id: str,
    word_index: int,
) -> ClipCaptionsResponse:
    load_project(project_id)
    target = resolve_caption_target(project_id, clip_id)
    existing = _load_captions_for_target(project_id, target)
    updated = delete_caption_word(
        existing.segments,
        segment_id=segment_id,
        word_index=word_index,
        clip_duration=target.duration,
    )
    document = existing.model_copy(update={"segments": updated, "updated_at": utc_now_iso()})
    _write_captions_document(document)
    return _document_to_response(document)
