from __future__ import annotations

import struct
import wave
from dataclasses import dataclass
from pathlib import Path

from app.models.project import TranscriptSegment


@dataclass(frozen=True)
class EnergyWindow:
    start: float
    end: float
    rms: float


@dataclass(frozen=True)
class PossibleSpeechRegion:
    start: float
    end: float
    rms: float
    reason: str


def analyze_audio_energy(
    wav_path: Path,
    *,
    window_seconds: float = 0.25,
) -> list[EnergyWindow]:
    with wave.open(str(wav_path), "rb") as handle:
        sample_rate = handle.getframerate()
        sample_width = handle.getsampwidth()
        if sample_width != 2:
            return []
        frame_count = handle.getnframes()
        frames = handle.readframes(frame_count)

    if not frames or sample_rate <= 0:
        return []

    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    window_size = max(1, int(sample_rate * window_seconds))
    windows: list[EnergyWindow] = []

    for index in range(0, len(samples), window_size):
        chunk = samples[index : index + window_size]
        if not chunk:
            continue
        rms = (sum(sample * sample for sample in chunk) / len(chunk)) ** 0.5 / 32768.0
        start = index / sample_rate
        end = min(len(samples), index + window_size) / sample_rate
        windows.append(EnergyWindow(start=round(start, 3), end=round(end, 3), rms=round(rms, 6)))

    return windows


def _word_ranges(segments: list[TranscriptSegment]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                ranges.append((word.start, word.end))
        else:
            ranges.append((segment.start, segment.end))
    return sorted(ranges)


def _overlaps_transcript(start: float, end: float, ranges: list[tuple[float, float]]) -> bool:
    for range_start, range_end in ranges:
        if end > range_start and start < range_end:
            return True
    return False


def find_possible_speech_without_transcript(
    energy_windows: list[EnergyWindow],
    segments: list[TranscriptSegment],
    *,
    min_duration: float = 0.35,
    energy_ratio: float = 2.0,
    absolute_rms_floor: float = 0.008,
) -> list[PossibleSpeechRegion]:
    if not energy_windows:
        return []

    noise_floor = sorted(window.rms for window in energy_windows)[len(energy_windows) // 4]
    threshold = max(absolute_rms_floor, noise_floor * energy_ratio)
    transcript_ranges = _word_ranges(segments)

    regions: list[PossibleSpeechRegion] = []
    active_start: float | None = None
    active_rms = 0.0

    for window in energy_windows:
        if window.rms >= threshold:
            if active_start is None:
                active_start = window.start
                active_rms = window.rms
            else:
                active_rms = max(active_rms, window.rms)
            continue

        if active_start is not None:
            region_end = window.start
            if region_end - active_start >= min_duration and not _overlaps_transcript(
                active_start,
                region_end,
                transcript_ranges,
            ):
                regions.append(
                    PossibleSpeechRegion(
                        start=round(active_start, 3),
                        end=round(region_end, 3),
                        rms=round(active_rms, 6),
                        reason="audio energy without transcript words",
                    )
                )
            active_start = None
            active_rms = 0.0

    if active_start is not None:
        region_end = energy_windows[-1].end
        if region_end - active_start >= min_duration and not _overlaps_transcript(
            active_start,
            region_end,
            transcript_ranges,
        ):
            regions.append(
                PossibleSpeechRegion(
                    start=round(active_start, 3),
                    end=round(region_end, 3),
                    rms=round(active_rms, 6),
                    reason="audio energy without transcript words",
                )
            )

    return regions


def longest_transcript_gap(segments: list[TranscriptSegment], *, duration: float) -> float:
    if duration <= 0:
        return 0.0
    if not segments:
        return duration

    sorted_segments = sorted(segments, key=lambda item: item.start)
    longest = sorted_segments[0].start
    for left, right in zip(sorted_segments, sorted_segments[1:]):
        longest = max(longest, right.start - left.end)
    longest = max(longest, duration - sorted_segments[-1].end)
    return round(longest, 3)
