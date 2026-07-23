from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.models.project import (
    CaptionSegment,
    CaptionStyle,
    CaptionWord,
    ClipCaptionsDocument,
    ClipCaptionsResponse,
    DeleteCaptionsResponse,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
    UpdateCaptionSegmentRequest,
    utc_now_iso,
)
from app.services.clip_export import ClipExportNotFoundError, locate_exported_clip
from app.services.project_store import get_clip_captions_path, load_project
from app.services.transcription import TranscriptNotFoundError, load_project_transcript


class ClipCaptionsValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipCaptionsNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipCaptionsGenerationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _round_time(value: float) -> float:
    return round(value, 3)


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
    for segment in segments:
        if segment.start < 0:
            raise ClipCaptionsValidationError(
                f"Caption {segment.id} start time must be non-negative."
            )
        if segment.end <= segment.start:
            raise ClipCaptionsValidationError(
                f"Caption {segment.id} end time must be after start time."
            )
        if segment.end > clip_duration + 0.001:
            raise ClipCaptionsValidationError(
                f"Caption {segment.id} end time exceeds clip duration ({clip_duration:.3f}s)."
            )
        for word in segment.words:
            if word.start < 0:
                raise ClipCaptionsValidationError(
                    f"Caption {segment.id} word start time must be non-negative."
                )
            if word.end <= word.start:
                raise ClipCaptionsValidationError(
                    f"Caption {segment.id} word end time must be after start time."
                )
            if word.end > clip_duration + 0.001:
                raise ClipCaptionsValidationError(
                    f"Caption {segment.id} word end time exceeds clip duration."
                )


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
    locate_exported_clip(project_id, clip_id)
    document = _load_captions_document(project_id, clip_id)
    return _document_to_response(document)


def generate_clip_captions(project_id: str, clip_id: str) -> ClipCaptionsResponse:
    load_project(project_id)
    record, _clip_path = locate_exported_clip(project_id, clip_id)

    try:
        transcript = load_project_transcript(project_id)
    except TranscriptNotFoundError as exc:
        raise ClipCaptionsGenerationError(
            "No transcript available. Transcribe the project before generating captions."
        ) from exc

    segments = extract_caption_segments_from_transcript(
        transcript,
        record.start_time,
        record.end_time,
    )
    if not segments:
        raise ClipCaptionsGenerationError(
            "No transcript content overlaps this clip's time range."
        )

    _validate_caption_segments(segments, record.duration)

    now = utc_now_iso()
    document = ClipCaptionsDocument(
        project_id=project_id,
        clip_id=clip_id,
        source_start_time=record.start_time,
        source_end_time=record.end_time,
        duration=record.duration,
        candidate_id=record.candidate_id,
        segments=segments,
        style=_default_caption_style(),
        created_at=now,
        updated_at=now,
    )
    _write_captions_document(document)
    return _document_to_response(document)


def update_clip_captions(
    project_id: str,
    clip_id: str,
    segment_updates: list[UpdateCaptionSegmentRequest],
) -> ClipCaptionsResponse:
    load_project(project_id)
    record, _clip_path = locate_exported_clip(project_id, clip_id)
    existing = _load_captions_document(project_id, clip_id)

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
            )
        )

    _validate_caption_segments(updated_segments, record.duration)

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
    locate_exported_clip(project_id, clip_id)

    deleted = delete_clip_captions(project_id, clip_id)
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
    locate_exported_clip(project_id, clip_id)
    existing = _load_captions_document(project_id, clip_id)

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
    locate_exported_clip(project_id, clip_id)
    existing = _load_captions_document(project_id, clip_id)

    document = existing.model_copy(
        update={
            "style": _default_caption_style(),
            "updated_at": utc_now_iso(),
        }
    )
    _write_captions_document(document)
    return _document_to_response(document)
