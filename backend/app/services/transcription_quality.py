from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.project import TranscriptSegment, TranscriptWord
from app.services.transcription_config import TranscriptionModeConfig


class TranscriptionQualityRating(str, Enum):
    GOOD = "good"
    REVIEW_RECOMMENDED = "review_recommended"
    POOR = "poor"


@dataclass
class SuspiciousRegion:
    start: float
    end: float
    reason: str
    severity: str = "warning"


@dataclass
class TranscriptionQualityResult:
    rating: TranscriptionQualityRating
    warnings: list[str] = field(default_factory=list)
    suspicious_regions: list[SuspiciousRegion] = field(default_factory=list)
    overlapping_speech_regions: list[SuspiciousRegion] = field(default_factory=list)
    low_confidence_word_count: int = 0
    average_word_probability: float | None = None


LOW_CONFIDENCE_THRESHOLD = 0.55
SUSPICIOUS_GAP_SECONDS = 1.5
SHORT_OMITTED_GAP_SECONDS = 0.35
OVERLAP_DENSITY_THRESHOLD = 0.12


def _round_time(value: float) -> float:
    return round(value, 3)


def analyze_transcription_quality(
    segments: list[TranscriptSegment],
    *,
    clip_start: float | None = None,
    clip_end: float | None = None,
    duration: float | None = None,
) -> TranscriptionQualityResult:
    warnings: list[str] = []
    suspicious_regions: list[SuspiciousRegion] = []
    overlapping_regions: list[SuspiciousRegion] = []

    all_words: list[TranscriptWord] = []
    for segment in segments:
        all_words.extend(segment.words)

    probabilities = [word.probability for word in all_words if word.probability is not None]
    low_confidence_count = sum(
        1 for probability in probabilities if probability < LOW_CONFIDENCE_THRESHOLD
    )
    average_probability = (
        round(sum(probabilities) / len(probabilities), 4) if probabilities else None
    )

    if low_confidence_count > 0:
        warnings.append(f"Low-confidence transcription detected ({low_confidence_count} words).")

    if clip_start is not None and segments:
        first_start = min(segment.start for segment in segments)
        if first_start <= clip_start + 0.15:
            warnings.append("Clip-boundary speech detected near start.")
            suspicious_regions.append(
                SuspiciousRegion(
                    start=max(0.0, first_start - 0.1),
                    end=first_start + 0.5,
                    reason="possible clip-boundary speech",
                )
            )

    if clip_end is not None and segments:
        last_end = max(segment.end for segment in segments)
        if last_end >= clip_end - 0.15:
            warnings.append("Clip-boundary speech detected near end.")
            suspicious_regions.append(
                SuspiciousRegion(
                    start=max(0.0, last_end - 0.5),
                    end=last_end + 0.1,
                    reason="possible clip-boundary speech",
                )
            )

    sorted_segments = sorted(segments, key=lambda item: item.start)
    for left, right in zip(sorted_segments, sorted_segments[1:]):
        gap = right.start - left.end
        if gap >= SUSPICIOUS_GAP_SECONDS:
            suspicious_regions.append(
                SuspiciousRegion(
                    start=_round_time(left.end),
                    end=_round_time(right.start),
                    reason="unusually long silence gap",
                )
            )
            warnings.append("Possible missing speech in long silence gap.")
        elif 0 < gap <= SHORT_OMITTED_GAP_SECONDS:
            suspicious_regions.append(
                SuspiciousRegion(
                    start=_round_time(left.end),
                    end=_round_time(right.start),
                    reason="short omitted region between segments",
                )
            )

    overlap_count = 0
    for left_index, left in enumerate(sorted_segments):
        for right in sorted_segments[left_index + 1 :]:
            if right.start < left.end:
                overlap_count += 1
                overlapping_regions.append(
                    SuspiciousRegion(
                        start=_round_time(right.start),
                        end=_round_time(min(left.end, right.end)),
                        reason="overlapping speech — review recommended",
                    )
                )

    if overlapping_regions:
        warnings.append("Overlapping speakers detected or suspected.")

    if not segments and duration and duration > 0.5:
        warnings.append("Speech-like audio may have no transcript result.")
        suspicious_regions.append(
            SuspiciousRegion(start=0.0, end=min(duration, 2.0), reason="no transcript result")
        )

    rating = TranscriptionQualityRating.GOOD
    if warnings or suspicious_regions:
        rating = TranscriptionQualityRating.REVIEW_RECOMMENDED
    if (
        low_confidence_count >= max(3, len(all_words) // 4)
        or len(suspicious_regions) >= 3
        or (not segments and duration and duration > 1.0)
    ):
        rating = TranscriptionQualityRating.POOR

    return TranscriptionQualityResult(
        rating=rating,
        warnings=warnings,
        suspicious_regions=suspicious_regions,
        overlapping_speech_regions=overlapping_regions,
        low_confidence_word_count=low_confidence_count,
        average_word_probability=average_probability,
    )


@dataclass
class RecoveryRegion:
    start: float
    end: float
    reason: str


def identify_recovery_regions(
    segments: list[TranscriptSegment],
    *,
    duration: float,
    mode_config: TranscriptionModeConfig,
) -> list[RecoveryRegion]:
    if not mode_config.enable_recovery_pass:
        return []

    quality = analyze_transcription_quality(segments, duration=duration)
    regions: list[RecoveryRegion] = []
    for region in quality.suspicious_regions:
        if region.end - region.start <= 0:
            continue
        regions.append(
            RecoveryRegion(start=region.start, end=region.end, reason=region.reason)
        )

    bounded: list[RecoveryRegion] = []
    total_duration = 0.0
    for region in regions:
        if len(bounded) >= mode_config.max_recovery_regions:
            break
        length = region.end - region.start
        if length <= 0:
            continue
        if total_duration + length > mode_config.max_recovery_duration_seconds:
            remaining = mode_config.max_recovery_duration_seconds - total_duration
            if remaining <= 0.2:
                break
            region = RecoveryRegion(
                start=region.start,
                end=region.start + remaining,
                reason=region.reason,
            )
            length = remaining
        bounded.append(region)
        total_duration += length
    return bounded


def merge_transcript_segments(
    primary: list[TranscriptSegment],
    recovered: list[TranscriptSegment],
    *,
    replace_start: float,
    replace_end: float,
) -> list[TranscriptSegment]:
    preserved = [
        segment
        for segment in primary
        if segment.end <= replace_start or segment.start >= replace_end
    ]
    merged = sorted([*preserved, *recovered], key=lambda item: (item.start, item.end))
    deduped: list[TranscriptSegment] = []
    for segment in merged:
        if deduped:
            previous = deduped[-1]
            if (
                previous.text.strip().lower() == segment.text.strip().lower()
                and abs(previous.start - segment.start) < 0.05
            ):
                continue
        deduped.append(segment)

    for index, segment in enumerate(deduped):
        segment.id = index
    return deduped


def merge_words_without_duplicates(
    existing: list[TranscriptWord],
    recovered: list[TranscriptWord],
) -> list[TranscriptWord]:
    merged = sorted([*existing, *recovered], key=lambda item: (item.start, item.end))
    deduped: list[TranscriptWord] = []
    for word in merged:
        if deduped:
            previous = deduped[-1]
            if (
                previous.word.strip().lower() == word.word.strip().lower()
                and abs(previous.start - word.start) < 0.05
            ):
                continue
        deduped.append(word)
    return deduped
