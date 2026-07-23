from __future__ import annotations

from dataclasses import dataclass

from app.models.project import TranscriptSegment, TranscriptWord


DEFAULT_CLIP_BOUNDARY_PADDING_SECONDS = 0.75


@dataclass(frozen=True)
class PaddedClipRange:
    clip_start: float
    clip_end: float
    padded_start: float
    padded_end: float
    source_duration: float


def compute_padded_range(
    clip_start: float,
    clip_end: float,
    source_duration: float,
    *,
    padding_seconds: float = DEFAULT_CLIP_BOUNDARY_PADDING_SECONDS,
) -> PaddedClipRange:
    padded_start = max(0.0, clip_start - padding_seconds)
    padded_end = min(source_duration, clip_end + padding_seconds)
    if padded_end <= padded_start:
        padded_end = min(source_duration, clip_start + 0.001)
    return PaddedClipRange(
        clip_start=clip_start,
        clip_end=clip_end,
        padded_start=padded_start,
        padded_end=padded_end,
        source_duration=source_duration,
    )


def _round_time(value: float) -> float:
    return round(value, 3)


def _segments_overlap(start: float, end: float, range_start: float, range_end: float) -> bool:
    return end > range_start and start < range_end


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def filter_words_to_clip_range(
    words: list[TranscriptWord],
    clip_start: float,
    clip_end: float,
) -> list[TranscriptWord]:
    filtered: list[TranscriptWord] = []
    for word in words:
        if not _segments_overlap(word.start, word.end, clip_start, clip_end):
            continue
        clamped_start = _clamp(word.start, clip_start, clip_end)
        clamped_end = _clamp(word.end, clip_start, clip_end)
        if clamped_end <= clamped_start:
            continue
        filtered.append(
            TranscriptWord(
                word=word.word,
                start=_round_time(clamped_start),
                end=_round_time(clamped_end),
                probability=word.probability,
            )
        )
    return filtered


def remap_words_to_clip_relative(
    words: list[TranscriptWord],
    clip_start: float,
    clip_end: float,
) -> list[TranscriptWord]:
    filtered = filter_words_to_clip_range(words, clip_start, clip_end)
    relative: list[TranscriptWord] = []
    for word in filtered:
        relative_start = _round_time(word.start - clip_start)
        relative_end = _round_time(word.end - clip_start)
        if relative_end <= relative_start or relative_start < 0:
            continue
        relative.append(
            TranscriptWord(
                word=word.word,
                start=relative_start,
                end=relative_end,
                probability=word.probability,
            )
        )
    return relative


def filter_segments_to_clip_range(
    segments: list[TranscriptSegment],
    clip_start: float,
    clip_end: float,
) -> list[TranscriptSegment]:
    filtered: list[TranscriptSegment] = []
    for index, segment in enumerate(segments):
        if not _segments_overlap(segment.start, segment.end, clip_start, clip_end):
            continue
        words = filter_words_to_clip_range(segment.words, clip_start, clip_end)
        if words:
            text = " ".join(word.word for word in words).strip()
            start = words[0].start
            end = words[-1].end
        else:
            text = segment.text.strip()
            start = _clamp(segment.start, clip_start, clip_end)
            end = _clamp(segment.end, clip_start, clip_end)
        if end <= start:
            continue
        filtered.append(
            TranscriptSegment(
                id=index,
                start=_round_time(start),
                end=_round_time(end),
                text=text,
                words=words,
            )
        )
    return filtered


def remap_segments_to_clip_relative(
    segments: list[TranscriptSegment],
    clip_start: float,
    clip_end: float,
) -> list[TranscriptSegment]:
    filtered = filter_segments_to_clip_range(segments, clip_start, clip_end)
    relative: list[TranscriptSegment] = []
    for index, segment in enumerate(filtered):
        relative_words = remap_words_to_clip_relative(segment.words, clip_start, clip_end)
        if relative_words:
            text = " ".join(word.word for word in relative_words).strip()
            start = relative_words[0].start
            end = relative_words[-1].end
        else:
            text = segment.text.strip()
            start = _round_time(segment.start - clip_start)
            end = _round_time(segment.end - clip_start)
        if end <= start or start < 0:
            continue
        relative.append(
            TranscriptSegment(
                id=index,
                start=start,
                end=end,
                text=text,
                words=relative_words,
            )
        )
    return relative
