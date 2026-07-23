from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.audio_preprocessing import PreprocessingMode, prepare_audio_for_transcription
from app.services.transcription_config import (
    CONSERVATIVE_VAD_PARAMETERS,
    ResolvedTranscriptionSettings,
    build_decode_options,
    get_mode_config,
    resolve_transcription_settings,
)
from app.services.transcription_pipeline import run_transcription_pass

logger = logging.getLogger(__name__)

DIAGNOSTIC_VARIANTS: list[dict[str, Any]] = [
    {"variant": "original_no_vad", "preprocessing": PreprocessingMode.ORIGINAL, "vad": False},
    {"variant": "normalized_no_vad", "preprocessing": PreprocessingMode.NORMALIZED, "vad": False},
    {"variant": "speech_filtered_no_vad", "preprocessing": PreprocessingMode.SPEECH_FILTERED, "vad": False},
    {"variant": "original_vad", "preprocessing": PreprocessingMode.ORIGINAL, "vad": True},
    {"variant": "normalized_vad", "preprocessing": PreprocessingMode.NORMALIZED, "vad": True},
]


def run_transcription_diagnostics(
    *,
    resolved: ResolvedTranscriptionSettings,
    source_audio_path: Path,
    temp_dir: Path,
    clip_start: float | None = None,
    clip_end: float | None = None,
) -> list[dict[str, Any]]:
    mode_config = get_mode_config(resolved.mode)
    results: list[dict[str, Any]] = []
    clip_timestamps = None
    if clip_start is not None and clip_end is not None and clip_end > clip_start:
        clip_timestamps = [clip_start, clip_end]

    for spec in DIAGNOSTIC_VARIANTS:
        preprocessing = spec["preprocessing"]
        vad_enabled = spec["vad"]
        variant_dir = temp_dir / spec["variant"]
        audio_path, prep_warnings, used_fallback = prepare_audio_for_transcription(
            source_audio_path,
            temp_dir=variant_dir,
            mode=preprocessing,
        )
        decode_options = build_decode_options(
            mode_config=mode_config,
            language=resolved.decode_options.get("language"),
            initial_prompt=resolved.decode_options.get("initial_prompt"),
            vad_filter=vad_enabled,
        )
        try:
            pass_result = run_transcription_pass(
                resolved=resolved,
                audio_path=audio_path,
                mode_config=mode_config,
                variant=spec["variant"],
                preprocessing_mode=preprocessing,
                vad_filter=vad_enabled,
                decode_options=decode_options,
                clip_timestamps=clip_timestamps,
            )
            payload = {
                "variant": spec["variant"],
                "model": pass_result.model,
                "requested_model": pass_result.requested_model,
                "device": pass_result.device,
                "compute_type": pass_result.compute_type,
                "quality_mode": resolved.mode.value,
                "preprocessing_mode": preprocessing.value,
                "preprocessing_fallback": used_fallback,
                "vad_enabled": vad_enabled,
                "vad_parameters": CONSERVATIVE_VAD_PARAMETERS if vad_enabled else None,
                "detected_language": pass_result.language,
                "duration_seconds": pass_result.duration,
                "segment_count": pass_result.coverage.segment_count if pass_result.coverage else 0,
                "word_count": pass_result.word_count,
                "text": pass_result.text,
                "warnings": [*prep_warnings, *pass_result.warnings],
                "coverage": asdict(pass_result.coverage) if pass_result.coverage else None,
                "segments": [
                    {
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text,
                        "avg_logprob": diag.avg_logprob,
                        "no_speech_prob": diag.no_speech_prob,
                        "compression_ratio": diag.compression_ratio,
                        "words": diag.words,
                    }
                    for segment, diag in zip(
                        pass_result.segments,
                        pass_result.segment_diagnostics,
                        strict=False,
                    )
                ],
            }
            logger.info(
                "Diagnostic variant=%s words=%s segments=%s vad=%s preprocessing=%s",
                spec["variant"],
                pass_result.word_count,
                len(pass_result.segments),
                vad_enabled,
                preprocessing.value,
            )
            results.append(payload)
        except Exception as exc:
            logger.warning("Diagnostic variant %s failed: %s", spec["variant"], exc)
            results.append(
                {
                    "variant": spec["variant"],
                    "error": str(exc),
                    "preprocessing_mode": preprocessing.value,
                    "vad_enabled": vad_enabled,
                }
            )

    return results


def run_transcription_diagnostics_for_project(
    *,
    project_id: str,
    source_audio_path: Path,
    temp_dir: Path,
    quality_mode: str | None = None,
    language: str | None = None,
    vocabulary_hints: str | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
) -> list[dict[str, Any]]:
    resolved = resolve_transcription_settings(
        quality_mode=quality_mode,
        language=language,
        vocabulary_hints=vocabulary_hints,
    )
    return run_transcription_diagnostics(
        resolved=resolved,
        source_audio_path=source_audio_path,
        temp_dir=temp_dir,
        clip_start=clip_start,
        clip_end=clip_end,
    )
