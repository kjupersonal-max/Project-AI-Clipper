from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.project import CaptionSegment, CaptionWord, utc_now_iso
from app.services.caption_validation import ClipCaptionsValidationError, round_caption_time, validate_caption_segments

_round_time = round_caption_time
_validate_caption_segments = validate_caption_segments


@dataclass
class ManualEditWarning:
    segment_id: str
    message: str


def mark_segment_manually_edited(
    segment: CaptionSegment,
    *,
    original_text: str | None = None,
) -> CaptionSegment:
    updates: dict = {"updated_at": utc_now_iso(), "manually_edited": True}
    if original_text and not segment.original_transcription_text:
        updates["original_transcription_text"] = original_text
    return segment.model_copy(update=updates)


def segment_has_manual_edits(segment: CaptionSegment) -> bool:
    return segment.manually_edited


def find_manual_edits_in_range(
    segments: list[CaptionSegment],
    range_start: float,
    range_end: float,
) -> list[ManualEditWarning]:
    warnings: list[ManualEditWarning] = []
    for segment in segments:
        if not segment_has_manual_edits(segment):
            continue
        if segment.end <= range_start or segment.start >= range_end:
            continue
        warnings.append(
            ManualEditWarning(
                segment_id=segment.id,
                message=f"Caption segment '{segment.text[:40]}' was manually edited.",
            )
        )
    return warnings


def insert_caption_word(
    segments: list[CaptionSegment],
    *,
    segment_id: str,
    word: str,
    start: float,
    end: float,
    clip_duration: float,
) -> list[CaptionSegment]:
    if end <= start:
        raise ClipCaptionsValidationError("Word end time must be after start time.")
    if start < 0 or end > clip_duration + 0.001:
        raise ClipCaptionsValidationError("Word timing must remain inside clip duration.")

    updated: list[CaptionSegment] = []
    for segment in segments:
        if segment.id != segment_id:
            updated.append(segment)
            continue

        words = sorted(
            [
                *segment.words,
                CaptionWord(word=word.strip(), start=_round_time(start), end=_round_time(end)),
            ],
            key=lambda item: item.start,
        )
        text = " ".join(item.word for item in words).strip()
        updated.append(
            mark_segment_manually_edited(
                segment.model_copy(
                    update={
                        "words": words,
                        "text": text,
                        "start": words[0].start,
                        "end": words[-1].end,
                        "updated_at": utc_now_iso(),
                    }
                ),
                original_text=segment.text,
            )
        )
    _validate_caption_segments(updated, clip_duration)
    return updated


def insert_caption_segment(
    segments: list[CaptionSegment],
    *,
    text: str,
    start: float,
    end: float,
    clip_duration: float,
) -> list[CaptionSegment]:
    cleaned = text.strip()
    if not cleaned:
        raise ClipCaptionsValidationError("Caption text cannot be empty.")
    if end <= start:
        raise ClipCaptionsValidationError("Segment end time must be after start time.")
    if start < 0 or end > clip_duration + 0.001:
        raise ClipCaptionsValidationError("Segment timing must remain inside clip duration.")

    now = utc_now_iso()
    new_segment = CaptionSegment(
        id=str(uuid.uuid4()),
        text=cleaned,
        start=_round_time(start),
        end=_round_time(end),
        words=[],
        sequence=len(segments),
        created_at=now,
        updated_at=now,
        manually_edited=True,
        original_transcription_text="",
    )
    updated = sorted([*segments, new_segment], key=lambda item: item.start)
    for index, segment in enumerate(updated):
        segment.sequence = index
    _validate_caption_segments(updated, clip_duration)
    return updated


def split_caption_segment(
    segments: list[CaptionSegment],
    *,
    segment_id: str,
    split_time: float,
    clip_duration: float,
) -> list[CaptionSegment]:
    updated: list[CaptionSegment] = []
    for segment in segments:
        if segment.id != segment_id:
            updated.append(segment)
            continue
        if split_time <= segment.start or split_time >= segment.end:
            raise ClipCaptionsValidationError("Split time must be inside the segment.")

        left_words = [word for word in segment.words if word.end <= split_time]
        right_words = [word for word in segment.words if word.start >= split_time]
        left_text = " ".join(word.word for word in left_words).strip() or segment.text[: len(segment.text) // 2].strip()
        right_text = " ".join(word.word for word in right_words).strip() or segment.text[len(segment.text) // 2 :].strip()
        if not left_text or not right_text:
            raise ClipCaptionsValidationError("Split would create an empty caption segment.")

        now = utc_now_iso()
        left = mark_segment_manually_edited(
            segment.model_copy(
                update={
                    "text": left_text,
                    "start": segment.start,
                    "end": _round_time(split_time),
                    "words": left_words,
                    "updated_at": now,
                }
            ),
            original_text=segment.text,
        )
        right = CaptionSegment(
            id=str(uuid.uuid4()),
            text=right_text,
            start=_round_time(split_time),
            end=segment.end,
            words=right_words,
            sequence=segment.sequence + 1,
            created_at=now,
            updated_at=now,
            manually_edited=True,
            original_transcription_text=segment.text,
        )
        updated.extend([left, right])

    updated.sort(key=lambda item: item.start)
    for index, segment in enumerate(updated):
        segment.sequence = index
    _validate_caption_segments(updated, clip_duration)
    return updated


def merge_caption_segments(
    segments: list[CaptionSegment],
    *,
    first_segment_id: str,
    second_segment_id: str,
    clip_duration: float,
) -> list[CaptionSegment]:
    first = next((segment for segment in segments if segment.id == first_segment_id), None)
    second = next((segment for segment in segments if segment.id == second_segment_id), None)
    if first is None or second is None:
        raise ClipCaptionsValidationError("Both caption segments must exist to merge.")
    if first.id == second.id:
        raise ClipCaptionsValidationError("Cannot merge a segment with itself.")

    left, right = sorted([first, second], key=lambda item: item.start)
    words = sorted([*left.words, *right.words], key=lambda item: item.start)
    text = " ".join(word.word for word in words).strip() or f"{left.text} {right.text}".strip()
    now = utc_now_iso()
    merged = mark_segment_manually_edited(
        left.model_copy(
            update={
                "text": text,
                "start": left.start,
                "end": right.end,
                "words": words,
                "updated_at": now,
            }
        ),
        original_text=left.text,
    )
    updated = [segment for segment in segments if segment.id not in {left.id, right.id}]
    updated.append(merged)
    updated.sort(key=lambda item: item.start)
    for index, segment in enumerate(updated):
        segment.sequence = index
    _validate_caption_segments(updated, clip_duration)
    return updated


def nudge_segment_timing(
    segments: list[CaptionSegment],
    *,
    segment_id: str,
    delta_seconds: float,
    clip_duration: float,
) -> list[CaptionSegment]:
    updated: list[CaptionSegment] = []
    for segment in segments:
        if segment.id != segment_id:
            updated.append(segment)
            continue
        new_start = _round_time(max(0.0, segment.start + delta_seconds))
        new_end = _round_time(min(clip_duration, segment.end + delta_seconds))
        if new_end <= new_start:
            raise ClipCaptionsValidationError("Adjusted timing is invalid.")
        words = [
            CaptionWord(
                word=word.word,
                start=_round_time(max(0.0, word.start + delta_seconds)),
                end=_round_time(min(clip_duration, word.end + delta_seconds)),
            )
            for word in segment.words
        ]
        updated.append(
            mark_segment_manually_edited(
                segment.model_copy(
                    update={
                        "start": new_start,
                        "end": new_end,
                        "words": words,
                        "updated_at": utc_now_iso(),
                    }
                ),
                original_text=segment.text,
            )
        )
    _validate_caption_segments(updated, clip_duration)
    return updated


def delete_caption_word(
    segments: list[CaptionSegment],
    *,
    segment_id: str,
    word_index: int,
    clip_duration: float,
) -> list[CaptionSegment]:
    updated: list[CaptionSegment] = []
    for segment in segments:
        if segment.id != segment_id:
            updated.append(segment)
            continue
        if word_index < 0 or word_index >= len(segment.words):
            raise ClipCaptionsValidationError("Word index out of range.")
        words = [word for index, word in enumerate(segment.words) if index != word_index]
        text = " ".join(word.word for word in words).strip()
        if not text:
            raise ClipCaptionsValidationError("Deleting this word would leave the caption empty.")
        updated.append(
            mark_segment_manually_edited(
                segment.model_copy(
                    update={
                        "words": words,
                        "text": text,
                        "start": words[0].start if words else segment.start,
                        "end": words[-1].end if words else segment.end,
                        "updated_at": utc_now_iso(),
                    }
                ),
                original_text=segment.text,
            )
        )
    _validate_caption_segments(updated, clip_duration)
    return updated
