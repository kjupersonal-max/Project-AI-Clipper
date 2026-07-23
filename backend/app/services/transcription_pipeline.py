from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.models.project import TranscriptSegment, TranscriptWord
from app.services.audio_cache import (
    get_cached_channel_levels,
    prepare_cached_audio_for_transcription,
    store_cached_channel_levels,
)
from app.services.audio_energy import (
    analyze_audio_energy,
    find_possible_speech_without_transcript,
    longest_transcript_gap,
)
from app.services.audio_preprocessing import (
    ChannelMixMode,
    PreprocessingMode,
    analyze_channel_levels,
)
from app.services.transcription_config import (
    CONSERVATIVE_VAD_PARAMETERS,
    PREPROCESSING_VERSION,
    ResolvedTranscriptionSettings,
    TranscriptionModeConfig,
    build_decode_options,
    get_mode_config,
)
from app.services.pipeline_timing import log_stage_event, log_timing_summary
from app.services.transcription_progress import (
    TranscriptionStage,
    noop_progress,
    stage_progress,
)
from app.services.transcription_quality import (
    RecoveryRegion,
    TranscriptionQualityRating,
    analyze_transcription_quality,
    identify_recovery_regions,
    merge_transcript_segments,
)

logger = logging.getLogger(__name__)

VAD_WORD_DROP_RATIO = 0.85
HALLUCINATION_COMPRESSION_RATIO = 2.8


@dataclass
class SegmentDiagnostics:
    id: int
    start: float
    end: float
    text: str
    avg_logprob: float | None
    no_speech_prob: float | None
    compression_ratio: float | None
    words: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CoverageMetrics:
    word_count: int
    segment_count: int
    spoken_region_coverage: float
    longest_unexplained_gap: float
    recovery_regions_attempted: int = 0
    recovered_words: int = 0
    duplicates_rejected: int = 0
    model_used: str = ""
    audio_variant: str = ""
    vad_state: bool = False
    preprocessing_mode: str = ""


@dataclass
class TranscriptionPassResult:
    variant: str
    segments: list[TranscriptSegment]
    language: str
    duration: float
    word_count: int
    text: str
    model: str
    requested_model: str
    device: str
    compute_type: str
    preprocessing_mode: str
    channel_mix: str
    vad_enabled: bool
    vad_parameters: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)
    coverage: CoverageMetrics | None = None
    segment_diagnostics: list[SegmentDiagnostics] = field(default_factory=list)


@dataclass
class MultipassTranscriptionResult:
    segments: list[TranscriptSegment]
    language: str
    duration: float
    warnings: list[str]
    coverage: CoverageMetrics
    resolved: ResolvedTranscriptionSettings
    passes: list[TranscriptionPassResult] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    skipped_passes: list[str] = field(default_factory=list)


def _word_count(segments: list[TranscriptSegment]) -> int:
    return sum(len(segment.words) if segment.words else len(segment.text.split()) for segment in segments)


def _flatten_text(segments: list[TranscriptSegment]) -> str:
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def _collect_words(segments: list[TranscriptSegment]) -> list[TranscriptWord]:
    words: list[TranscriptWord] = []
    for segment in segments:
        if segment.words:
            words.extend(segment.words)
    return words


def _spoken_coverage(segments: list[TranscriptSegment], duration: float) -> float:
    if duration <= 0:
        return 0.0
    covered = sum(max(0.0, segment.end - segment.start) for segment in segments)
    return round(min(1.0, covered / duration), 4)


def _iter_segments_with_diagnostics(segments_iter: Any) -> tuple[list[TranscriptSegment], list[SegmentDiagnostics]]:
    transcript_segments: list[TranscriptSegment] = []
    diagnostics: list[SegmentDiagnostics] = []
    for segment in segments_iter:
        words = [
            TranscriptWord(
                word=word.word.strip(),
                start=round(word.start, 3),
                end=round(word.end, 3),
                probability=round(word.probability, 4) if word.probability is not None else None,
            )
            for word in (segment.words or [])
            if word.word.strip()
        ]
        transcript_segments.append(
            TranscriptSegment(
                id=segment.id,
                start=round(segment.start, 3),
                end=round(segment.end, 3),
                text=segment.text.strip(),
                words=words,
            )
        )
        diagnostics.append(
            SegmentDiagnostics(
                id=segment.id,
                start=round(segment.start, 3),
                end=round(segment.end, 3),
                text=segment.text.strip(),
                avg_logprob=round(segment.avg_logprob, 4)
                if getattr(segment, "avg_logprob", None) is not None
                else None,
                no_speech_prob=round(segment.no_speech_prob, 4)
                if getattr(segment, "no_speech_prob", None) is not None
                else None,
                compression_ratio=round(segment.compression_ratio, 4)
                if getattr(segment, "compression_ratio", None) is not None
                else None,
                words=[
                    {
                        "word": word.word,
                        "start": round(word.start, 3),
                        "end": round(word.end, 3),
                        "probability": round(word.probability, 4)
                        if word.probability is not None
                        else None,
                    }
                    for word in (segment.words or [])
                    if word.word.strip()
                ],
            )
        )
    return transcript_segments, diagnostics


def _build_coverage(
    *,
    segments: list[TranscriptSegment],
    duration: float,
    resolved: ResolvedTranscriptionSettings,
    variant: str,
    preprocessing_mode: str,
    vad_enabled: bool,
    recovery_regions_attempted: int = 0,
    recovered_words: int = 0,
    duplicates_rejected: int = 0,
) -> CoverageMetrics:
    return CoverageMetrics(
        word_count=_word_count(segments),
        segment_count=len(segments),
        spoken_region_coverage=_spoken_coverage(segments, duration),
        longest_unexplained_gap=longest_transcript_gap(segments, duration=duration),
        recovery_regions_attempted=recovery_regions_attempted,
        recovered_words=recovered_words,
        duplicates_rejected=duplicates_rejected,
        model_used=resolved.model_size,
        audio_variant=variant,
        vad_state=vad_enabled,
        preprocessing_mode=preprocessing_mode,
    )


def _average_word_confidence(segments: list[TranscriptSegment]) -> float | None:
    probabilities = [
        word.probability
        for segment in segments
        for word in segment.words
        if word.probability is not None
    ]
    if not probabilities:
        return None
    return sum(probabilities) / len(probabilities)


def _primary_pass_sufficient(
    pass_result: TranscriptionPassResult,
    *,
    duration: float,
    mode_config: TranscriptionModeConfig,
) -> bool:
    if not pass_result.segments or duration <= 0:
        return False
    coverage = pass_result.coverage.spoken_region_coverage if pass_result.coverage else 0.0
    gap = pass_result.coverage.longest_unexplained_gap if pass_result.coverage else duration
    avg_confidence = _average_word_confidence(pass_result.segments)
    if coverage < mode_config.early_exit_min_coverage:
        return False
    if gap > mode_config.early_exit_max_gap_seconds:
        return False
    if avg_confidence is not None and avg_confidence < mode_config.early_exit_min_avg_confidence:
        return False
    quality = analyze_transcription_quality(pass_result.segments, duration=duration)
    if quality.rating == TranscriptionQualityRating.POOR:
        return False
    return True


def _needs_secondary_pass(
    pass_result: TranscriptionPassResult,
    *,
    duration: float,
    mode_config: TranscriptionModeConfig,
) -> bool:
    if _primary_pass_sufficient(pass_result, duration=duration, mode_config=mode_config):
        return False
    if not pass_result.segments:
        return True
    coverage = pass_result.coverage.spoken_region_coverage if pass_result.coverage else 0.0
    gap = pass_result.coverage.longest_unexplained_gap if pass_result.coverage else duration
    return (
        coverage < mode_config.early_exit_min_coverage
        or gap > mode_config.early_exit_max_gap_seconds
        or pass_result.word_count < max(3, int(duration * 0.4))
    )


def _merge_recovery_regions(
    regions: list[RecoveryRegion],
    *,
    merge_gap_seconds: float,
) -> list[RecoveryRegion]:
    if not regions:
        return []
    ordered = sorted(regions, key=lambda item: (item.start, item.end))
    merged: list[RecoveryRegion] = [ordered[0]]
    for region in ordered[1:]:
        previous = merged[-1]
        if region.start - previous.end <= merge_gap_seconds:
            merged[-1] = RecoveryRegion(
                start=previous.start,
                end=max(previous.end, region.end),
                reason=f"{previous.reason}; merged {region.reason}",
            )
        else:
            merged.append(region)
    return merged


def _bound_recovery_regions(
    regions: list[RecoveryRegion],
    *,
    duration: float,
    mode_config: TranscriptionModeConfig,
) -> list[RecoveryRegion]:
    max_total = min(
        mode_config.max_recovery_duration_seconds,
        duration * settings.transcription_max_recovery_coverage_ratio,
    )
    bounded: list[RecoveryRegion] = []
    total = 0.0
    for region in regions:
        if len(bounded) >= mode_config.max_recovery_regions:
            break
        length = max(0.0, region.end - region.start)
        if length <= 0:
            continue
        if total + length > max_total:
            remaining = max_total - total
            if remaining <= 0.2:
                break
            region = RecoveryRegion(region.start, region.start + remaining, region.reason)
            length = remaining
        bounded.append(region)
        total += length
    return bounded


def _score_transcript(segments: list[TranscriptSegment], duration: float) -> float:
    if not segments:
        return 0.0
    words = _collect_words(segments)
    word_score = len(words) if words else _word_count(segments)
    coverage = _spoken_coverage(segments, duration)
    probabilities = [word.probability for word in words if word.probability is not None]
    confidence_bonus = (sum(probabilities) / len(probabilities)) if probabilities else 0.5
    gap_penalty = longest_transcript_gap(segments, duration=duration) * 0.15
    return word_score * 0.55 + coverage * 20.0 + confidence_bonus * 5.0 - gap_penalty


def _is_hallucination_heavy(segments: list[TranscriptSegment], diagnostics: list[SegmentDiagnostics]) -> bool:
    if not diagnostics:
        return False
    suspicious = sum(
        1
        for item in diagnostics
        if item.compression_ratio is not None and item.compression_ratio >= HALLUCINATION_COMPRESSION_RATIO
    )
    return suspicious >= max(1, len(diagnostics) // 3)


def run_transcription_pass(
    *,
    resolved: ResolvedTranscriptionSettings,
    audio_path: Path,
    mode_config: TranscriptionModeConfig,
    variant: str,
    preprocessing_mode: PreprocessingMode,
    channel_mix: ChannelMixMode = ChannelMixMode.MONO,
    vad_filter: bool = False,
    decode_options: dict[str, Any] | None = None,
    clip_timestamps: list[float] | None = None,
    project_id: str | None = None,
) -> TranscriptionPassResult:
    pass_started = time.perf_counter()
    log_stage_event(
        "transcription_pass",
        "start",
        project_id=project_id,
        variant=variant,
        vad_filter=vad_filter,
        clip=clip_timestamps,
        model=resolved.model_size,
        device=resolved.device,
    )
    options = decode_options or build_decode_options(
        mode_config=mode_config,
        language=resolved.decode_options.get("language"),
        initial_prompt=resolved.decode_options.get("initial_prompt"),
        vad_filter=vad_filter,
        vad_parameters=CONSERVATIVE_VAD_PARAMETERS if vad_filter else None,
    )
    if clip_timestamps is not None:
        options = {**options, "clip_timestamps": clip_timestamps}

    from app.services.transcription import run_whisper_transcribe

    segments_iter, info, effective = run_whisper_transcribe(resolved, audio_path, **options)
    segments, segment_diagnostics = _iter_segments_with_diagnostics(segments_iter)
    duration = round(info.duration or 0.0, 3)
    language = info.language or "unknown"
    coverage = _build_coverage(
        segments=segments,
        duration=duration,
        resolved=effective,
        variant=variant,
        preprocessing_mode=preprocessing_mode.value,
        vad_enabled=vad_filter,
    )
    log_stage_event(
        "transcription_pass",
        "end",
        project_id=project_id,
        variant=variant,
        elapsed_seconds=time.perf_counter() - pass_started,
        word_count=coverage.word_count,
        segments=len(segments),
        duration=duration,
        effective_device=effective.device,
    )
    return TranscriptionPassResult(
        variant=variant,
        segments=segments,
        language=language,
        duration=duration,
        word_count=coverage.word_count,
        text=_flatten_text(segments),
        model=effective.model_size,
        requested_model=resolved.requested_model_size,
        device=effective.device,
        compute_type=effective.compute_type,
        preprocessing_mode=preprocessing_mode.value,
        channel_mix=channel_mix.value,
        vad_enabled=vad_filter,
        vad_parameters=CONSERVATIVE_VAD_PARAMETERS if vad_filter else None,
        coverage=coverage,
        segment_diagnostics=segment_diagnostics,
    )


def _merge_pass_results(
    candidates: list[TranscriptionPassResult],
    *,
    duration: float,
) -> TranscriptionPassResult:
    viable = [candidate for candidate in candidates if candidate.segments]
    if not viable:
        return candidates[0]
    ranked = sorted(viable, key=lambda item: _score_transcript(item.segments, duration), reverse=True)
    best = ranked[0]
    for candidate in ranked[1:]:
        if _is_hallucination_heavy(candidate.segments, candidate.segment_diagnostics):
            continue
        if _score_transcript(candidate.segments, duration) >= _score_transcript(best.segments, duration):
            best = candidate
    return best


def _compare_vad_vs_no_vad(
    no_vad: TranscriptionPassResult,
    with_vad: TranscriptionPassResult,
) -> tuple[TranscriptionPassResult, list[str]]:
    warnings: list[str] = []
    if with_vad.word_count >= no_vad.word_count:
        return no_vad, warnings
    if with_vad.word_count <= no_vad.word_count * VAD_WORD_DROP_RATIO:
        warnings.append(
            f"VAD removed possible speech ({with_vad.word_count} words vs {no_vad.word_count} without VAD)."
        )
        return no_vad, warnings
    return no_vad, warnings


def _recovery_regions_from_energy(
    audio_path: Path,
    segments: list[TranscriptSegment],
    *,
    duration: float,
    mode_config: TranscriptionModeConfig,
) -> list[RecoveryRegion]:
    energy = analyze_audio_energy(audio_path)
    possible = find_possible_speech_without_transcript(energy, segments)
    transcript_regions = identify_recovery_regions(segments, duration=duration, mode_config=mode_config)
    merged = _merge_recovery_regions(
        [
            *[
                RecoveryRegion(start=region.start, end=region.end, reason=region.reason)
                for region in transcript_regions
            ],
            *[
                RecoveryRegion(start=region.start, end=region.end, reason=region.reason)
                for region in possible
            ],
        ],
        merge_gap_seconds=settings.transcription_recovery_merge_gap_seconds,
    )
    return _bound_recovery_regions(merged, duration=duration, mode_config=mode_config)


def _apply_recovery_passes(
    *,
    base_segments: list[TranscriptSegment],
    resolved: ResolvedTranscriptionSettings,
    mode_config: TranscriptionModeConfig,
    audio_path: Path,
    duration: float,
    padding_seconds: float,
    progress: Callable[[str, float, str], None] = noop_progress,
    project_id: str | None = None,
) -> tuple[list[TranscriptSegment], int, int, list[str], dict[str, float]]:
    warnings: list[str] = []
    timings: dict[str, float] = {"recovery_total": 0.0}
    recovery_started = time.perf_counter()
    log_stage_event("recovery", "start", project_id=project_id, duration=f"{duration:.3f}s")
    if _primary_pass_sufficient(
        TranscriptionPassResult(
            variant="recovery_check",
            segments=base_segments,
            language="unknown",
            duration=duration,
            word_count=_word_count(base_segments),
            text=_flatten_text(base_segments),
            model=resolved.model_size,
            requested_model=resolved.requested_model_size,
            device=resolved.device,
            compute_type=resolved.compute_type,
            preprocessing_mode=mode_config.primary_preprocessing.value,
            channel_mix="mono",
            vad_enabled=False,
            vad_parameters=None,
            coverage=_build_coverage(
                segments=base_segments,
                duration=duration,
                resolved=resolved,
                variant="recovery_check",
                preprocessing_mode=mode_config.primary_preprocessing.value,
                vad_enabled=False,
            ),
        ),
        duration=duration,
        mode_config=mode_config,
    ):
        log_stage_event(
            "recovery",
            "skipped",
            project_id=project_id,
            reason="primary_sufficient",
            elapsed_seconds=time.perf_counter() - recovery_started,
        )
        return base_segments, 0, 0, warnings, timings

    regions = _recovery_regions_from_energy(
        audio_path,
        base_segments,
        duration=duration,
        mode_config=mode_config,
    )
    if not regions:
        log_stage_event(
            "recovery",
            "skipped",
            project_id=project_id,
            reason="no_regions",
            elapsed_seconds=time.perf_counter() - recovery_started,
        )
        return base_segments, 0, 0, warnings, timings

    merged_segments = base_segments
    recovered_words = 0
    duplicates_rejected = 0
    attempted: set[tuple[float, float]] = set()

    for index, region in enumerate(regions):
        region_key = (round(region.start, 2), round(region.end, 2))
        if region_key in attempted:
            continue
        attempted.add(region_key)

        progress(
            TranscriptionStage.RECOVERY_PASS.value,
            stage_progress(
                TranscriptionStage.RECOVERY_PASS,
                sub_progress=(index + 1) / max(1, len(regions)),
            ),
            f"Recovery region {index + 1}/{len(regions)}",
        )
        padded_start = max(0.0, region.start - padding_seconds)
        padded_end = min(duration, region.end + padding_seconds)
        started = time.perf_counter()
        pass_result = run_transcription_pass(
            resolved=resolved,
            audio_path=audio_path,
            mode_config=mode_config,
            variant=f"recovery_{region.start:.2f}_{region.end:.2f}",
            preprocessing_mode=mode_config.primary_preprocessing,
            vad_filter=False,
            decode_options=resolved.recovery_options,
            clip_timestamps=[padded_start, padded_end],
            project_id=project_id,
        )
        timings[f"recovery_{index}"] = round(time.perf_counter() - started, 3)
        before_words = _word_count(merged_segments)
        merged_segments = merge_transcript_segments(
            merged_segments,
            pass_result.segments,
            replace_start=region.start,
            replace_end=region.end,
        )
        after_words = _word_count(merged_segments)
        gained = max(0, after_words - before_words)
        recovered_words += gained
        if gained == 0 and pass_result.word_count > 0:
            duplicates_rejected += pass_result.word_count

    timings["recovery_total"] = round(sum(timings.values()), 3)
    if recovered_words > 0:
        warnings.append(f"Recovered {recovered_words} word(s) from suspected missing-speech regions.")
    log_stage_event(
        "recovery",
        "end",
        project_id=project_id,
        elapsed_seconds=time.perf_counter() - recovery_started,
        regions=len(regions),
        recovered_words=recovered_words,
        duplicates_rejected=duplicates_rejected,
    )
    return merged_segments, len(regions), recovered_words, warnings, timings


def _select_best_channel_audio(
    source_path: Path,
    temp_dir: Path,
    *,
    mode: PreprocessingMode,
) -> tuple[Path, ChannelMixMode, list[str]]:
    warnings: list[str] = []
    cached_levels = get_cached_channel_levels(source_path)
    if cached_levels is not None:
        channel_levels = cached_levels
    else:
        analyzed = analyze_channel_levels(source_path)
        channel_levels = [
            {
                "channel": item.channel,
                "peak_amplitude": item.peak_amplitude,
                "rms_level": item.rms_level,
            }
            for item in analyzed
        ]
        if channel_levels:
            store_cached_channel_levels(source_path, channel_levels)

    if len(channel_levels) >= 2:
        loudest = max(channel_levels, key=lambda item: float(item["rms_level"]))
        quietest = min(channel_levels, key=lambda item: float(item["rms_level"]))
        if float(loudest["rms_level"]) > max(float(quietest["rms_level"]) * 3.0, 0.01):
            warnings.append(
                f"Stereo imbalance detected ({quietest['channel']} quiet vs {loudest['channel']}); "
                f"preferring {loudest['channel']} channel."
            )
            mix = ChannelMixMode(str(loudest["channel"]))
            audio_path, prep_warnings, _used_fallback, _cache_hit = prepare_cached_audio_for_transcription(
                source_path,
                temp_dir=temp_dir,
                mode=mode,
                channel_mix=mix,
                preprocessing_version=PREPROCESSING_VERSION,
            )
            return audio_path, mix, [*warnings, *prep_warnings]

    audio_path, prep_warnings, _used_fallback, _cache_hit = prepare_cached_audio_for_transcription(
        source_path,
        temp_dir=temp_dir,
        mode=mode,
        channel_mix=ChannelMixMode.MONO,
        preprocessing_version=PREPROCESSING_VERSION,
    )
    return audio_path, ChannelMixMode.MONO, [*warnings, *prep_warnings]


def run_multipass_transcription(
    *,
    resolved: ResolvedTranscriptionSettings,
    source_audio_path: Path,
    temp_dir: Path,
    language: str | None = None,
    progress: Callable[[str, float, str], None] = noop_progress,
    project_id: str | None = None,
) -> MultipassTranscriptionResult:
    pipeline_started = time.perf_counter()
    timings: dict[str, float] = {}
    skipped_passes: list[str] = []
    mode_config = get_mode_config(resolved.mode)
    passes: list[TranscriptionPassResult] = []
    warnings = list(resolved.warnings)
    padding = settings.transcription_clip_boundary_padding_seconds

    log_stage_event(
        "multipass_transcription",
        "start",
        project_id=project_id,
        mode=resolved.mode.value,
        model=resolved.model_size,
        device=resolved.device,
        source=str(source_audio_path),
    )

    progress(TranscriptionStage.PREPARING_AUDIO.value, stage_progress(TranscriptionStage.PREPARING_AUDIO), "Preparing audio")
    log_stage_event("preprocessing", "start", project_id=project_id)
    prep_started = time.perf_counter()
    primary_audio, channel_mix, channel_warnings = _select_best_channel_audio(
        source_audio_path,
        temp_dir,
        mode=mode_config.primary_preprocessing,
    )
    timings["preprocessing"] = round(time.perf_counter() - prep_started, 3)
    log_stage_event(
        "preprocessing",
        "end",
        project_id=project_id,
        elapsed_seconds=timings["preprocessing"],
        channel_mix=channel_mix.value,
    )
    warnings.extend(channel_warnings)

    progress(TranscriptionStage.PRIMARY_TRANSCRIPTION.value, stage_progress(TranscriptionStage.PRIMARY_TRANSCRIPTION), "Primary transcription")
    log_stage_event("primary_transcription", "start", project_id=project_id, channel_mix=channel_mix.value)
    primary_started = time.perf_counter()
    primary_pass = run_transcription_pass(
        resolved=resolved,
        audio_path=primary_audio,
        mode_config=mode_config,
        variant="primary_no_vad",
        preprocessing_mode=mode_config.primary_preprocessing,
        channel_mix=channel_mix,
        vad_filter=False,
        decode_options=resolved.decode_options,
        project_id=project_id,
    )
    timings["primary_transcription"] = round(time.perf_counter() - primary_started, 3)
    log_stage_event(
        "primary_transcription",
        "end",
        project_id=project_id,
        elapsed_seconds=timings["primary_transcription"],
        word_count=primary_pass.word_count,
        segments=len(primary_pass.segments),
    )
    passes.append(primary_pass)

    progress(TranscriptionStage.EVALUATING_QUALITY.value, stage_progress(TranscriptionStage.EVALUATING_QUALITY), "Evaluating transcript quality")
    selected = primary_pass
    candidate_passes = [primary_pass]
    primary_sufficient = _primary_pass_sufficient(
        primary_pass,
        duration=primary_pass.duration,
        mode_config=mode_config,
    )
    primary_coverage = primary_pass.coverage
    log_stage_event(
        "early_exit_decision",
        "evaluated",
        project_id=project_id,
        primary_sufficient=primary_sufficient,
        coverage=f"{primary_coverage.spoken_region_coverage:.3f}" if primary_coverage else "n/a",
        gap=f"{primary_coverage.longest_unexplained_gap:.3f}" if primary_coverage else "n/a",
        word_count=primary_pass.word_count,
    )

    if mode_config.secondary_preprocessing is not None:
        if _needs_secondary_pass(primary_pass, duration=primary_pass.duration, mode_config=mode_config):
            progress(
                TranscriptionStage.SECONDARY_TRANSCRIPTION.value,
                stage_progress(TranscriptionStage.SECONDARY_TRANSCRIPTION),
                "Secondary transcription",
            )
            log_stage_event("secondary_transcription", "start", project_id=project_id)
            secondary_started = time.perf_counter()
            secondary_audio, secondary_warnings, _used_fallback, _cache_hit = prepare_cached_audio_for_transcription(
                source_audio_path,
                temp_dir=temp_dir / "secondary",
                mode=mode_config.secondary_preprocessing,
                channel_mix=channel_mix,
                preprocessing_version=PREPROCESSING_VERSION,
            )
            warnings.extend(secondary_warnings)
            secondary_pass = run_transcription_pass(
                resolved=resolved,
                audio_path=secondary_audio,
                mode_config=mode_config,
                variant="secondary_no_vad",
                preprocessing_mode=mode_config.secondary_preprocessing,
                channel_mix=channel_mix,
                vad_filter=False,
                decode_options=resolved.decode_options,
                project_id=project_id,
            )
            timings["secondary_transcription"] = round(time.perf_counter() - secondary_started, 3)
            log_stage_event(
                "secondary_transcription",
                "end",
                project_id=project_id,
                elapsed_seconds=timings["secondary_transcription"],
                word_count=secondary_pass.word_count,
                segments=len(secondary_pass.segments),
            )
            passes.append(secondary_pass)
            candidate_passes.append(secondary_pass)
        else:
            skipped_passes.append("secondary_no_vad")
            log_stage_event(
                "secondary_transcription",
                "skipped",
                project_id=project_id,
                reason="primary_sufficient_or_not_needed",
            )

    if mode_config.use_vad_recovery_pass and not primary_sufficient:
        log_stage_event("vad_transcription", "start", project_id=project_id)
        vad_started = time.perf_counter()
        vad_pass = run_transcription_pass(
            resolved=resolved,
            audio_path=primary_audio,
            mode_config=mode_config,
            variant="primary_vad",
            preprocessing_mode=mode_config.primary_preprocessing,
            channel_mix=channel_mix,
            vad_filter=True,
            decode_options=build_decode_options(
                mode_config=mode_config,
                language=resolved.decode_options.get("language"),
                initial_prompt=resolved.decode_options.get("initial_prompt"),
                vad_filter=True,
            ),
            project_id=project_id,
        )
        timings["vad_transcription"] = round(time.perf_counter() - vad_started, 3)
        log_stage_event(
            "vad_transcription",
            "end",
            project_id=project_id,
            elapsed_seconds=timings["vad_transcription"],
            word_count=vad_pass.word_count,
        )
        passes.append(vad_pass)
        selected, vad_warnings = _compare_vad_vs_no_vad(selected, vad_pass)
        warnings.extend(vad_warnings)
    elif mode_config.use_vad_recovery_pass:
        skipped_passes.append("primary_vad")
        log_stage_event("vad_transcription", "skipped", project_id=project_id, reason="primary_sufficient")

    if len(candidate_passes) > 1:
        progress(TranscriptionStage.MERGING_TRANSCRIPT.value, stage_progress(TranscriptionStage.MERGING_TRANSCRIPT), "Merging transcript passes")
        log_stage_event("transcript_merge", "start", project_id=project_id, passes=len(candidate_passes))
        merge_started = time.perf_counter()
        selected = _merge_pass_results(candidate_passes, duration=selected.duration)
        timings["transcript_merge"] = round(time.perf_counter() - merge_started, 3)
        log_stage_event(
            "transcript_merge",
            "end",
            project_id=project_id,
            elapsed_seconds=timings["transcript_merge"],
            selected_variant=selected.variant,
        )

    segments = selected.segments
    duration = selected.duration
    detected_language = selected.language

    recovery_regions = 0
    recovered_words = 0
    duplicates_rejected = 0
    if mode_config.enable_recovery_pass and not primary_sufficient:
        segments, recovery_regions, recovered_words, recovery_warnings, recovery_timings = _apply_recovery_passes(
            base_segments=segments,
            resolved=resolved,
            mode_config=mode_config,
            audio_path=primary_audio,
            duration=duration,
            padding_seconds=padding,
            progress=progress,
            project_id=project_id,
        )
        timings.update(recovery_timings)
        warnings.extend(recovery_warnings)
    elif mode_config.enable_recovery_pass:
        skipped_passes.append("recovery")
        log_stage_event("recovery", "skipped", project_id=project_id, reason="primary_sufficient")

    coverage = _build_coverage(
        segments=segments,
        duration=duration,
        resolved=resolved,
        variant=selected.variant,
        preprocessing_mode=selected.preprocessing_mode,
        vad_enabled=selected.vad_enabled,
        recovery_regions_attempted=recovery_regions,
        recovered_words=recovered_words,
        duplicates_rejected=duplicates_rejected,
    )

    quality = analyze_transcription_quality(segments, duration=duration)
    warnings.extend(quality.warnings)

    timings["total"] = round(time.perf_counter() - pipeline_started, 3)
    progress(TranscriptionStage.COMPLETED.value, 100.0, "Transcription complete")

    log_timing_summary(
        project_id=project_id,
        pipeline="multipass_transcription",
        total_seconds=timings["total"],
        mode=resolved.mode.value,
        model=resolved.model_size,
        device=resolved.device,
        variant=selected.variant,
        words=coverage.word_count,
        segments=coverage.segment_count,
        skipped=",".join(skipped_passes) or "none",
        preprocessing=f"{timings.get('preprocessing', 0.0):.3f}s",
        primary_transcription=f"{timings.get('primary_transcription', 0.0):.3f}s",
        secondary_transcription=f"{timings.get('secondary_transcription', 0.0):.3f}s",
        vad_transcription=f"{timings.get('vad_transcription', 0.0):.3f}s",
        recovery=f"{timings.get('recovery_total', 0.0):.3f}s",
        transcript_merge=f"{timings.get('transcript_merge', 0.0):.3f}s",
        timings=timings,
    )

    return MultipassTranscriptionResult(
        segments=segments,
        language=detected_language,
        duration=duration,
        warnings=warnings,
        coverage=coverage,
        resolved=resolved,
        passes=passes,
        timings=timings,
        skipped_passes=skipped_passes,
    )
