from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.project import TranscriptSegment, TranscriptionQualityMode
from app.services.transcription_config import MODE_CONFIGS, resolve_transcription_settings
from app.services.transcription_pipeline import (
    CoverageMetrics,
    TranscriptionPassResult,
    _bound_recovery_regions,
    _merge_recovery_regions,
    _needs_secondary_pass,
    _primary_pass_sufficient,
    run_multipass_transcription,
)
from app.services.transcription_quality import RecoveryRegion


def _pass_result(*, word_count: int = 20, coverage: float = 0.9, gap: float = 0.5) -> TranscriptionPassResult:
    segments = [
        TranscriptSegment(
            id=0,
            start=0.0,
            end=2.0,
            text="hello world",
            words=[],
        )
    ]
    return TranscriptionPassResult(
        variant="primary_no_vad",
        segments=segments,
        language="en",
        duration=10.0,
        word_count=word_count,
        text="hello world",
        model="small",
        requested_model="small",
        device="cpu",
        compute_type="int8",
        preprocessing_mode="original",
        channel_mix="mono",
        vad_enabled=False,
        vad_parameters=None,
        coverage=CoverageMetrics(
            word_count=word_count,
            segment_count=1,
            spoken_region_coverage=coverage,
            longest_unexplained_gap=gap,
        ),
    )


def test_primary_pass_sufficient_skips_secondary():
    mode_config = MODE_CONFIGS[TranscriptionQualityMode.BALANCED]
    result = _pass_result(coverage=0.9, gap=0.5)
    assert _primary_pass_sufficient(result, duration=10.0, mode_config=mode_config)
    assert not _needs_secondary_pass(result, duration=10.0, mode_config=mode_config)


def test_suspicious_transcript_triggers_secondary():
    mode_config = MODE_CONFIGS[TranscriptionQualityMode.BALANCED]
    result = _pass_result(word_count=2, coverage=0.2, gap=5.0)
    assert not _primary_pass_sufficient(result, duration=10.0, mode_config=mode_config)
    assert _needs_secondary_pass(result, duration=10.0, mode_config=mode_config)


def test_recovery_regions_are_merged():
    regions = [
        RecoveryRegion(1.0, 2.0, "gap"),
        RecoveryRegion(2.1, 3.0, "gap"),
        RecoveryRegion(5.0, 6.0, "energy"),
    ]
    merged = _merge_recovery_regions(regions, merge_gap_seconds=0.5)
    assert len(merged) == 2
    assert merged[0].start == 1.0
    assert merged[0].end == 3.0


def test_recovery_duration_is_capped_by_ratio():
    mode_config = MODE_CONFIGS[TranscriptionQualityMode.BALANCED]
    regions = [
        RecoveryRegion(0.0, 5.0, "a"),
        RecoveryRegion(6.0, 12.0, "b"),
        RecoveryRegion(13.0, 20.0, "c"),
    ]
    bounded = _bound_recovery_regions(regions, duration=100.0, mode_config=mode_config)
    total = sum(region.end - region.start for region in bounded)
    assert total <= 15.0 + 0.01


def test_multipass_skips_secondary_on_clean_primary(tmp_path: Path, monkeypatch):
    source = tmp_path / "audio.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")
    resolved = resolve_transcription_settings(quality_mode="balanced")

    def fake_run(resolved_in, audio_path, **options):
        segments = [
            SimpleNamespace(
                id=0,
                start=0.0,
                end=9.0,
                text=" lots of speech here",
                words=[SimpleNamespace(word=" lots", start=0.0, end=1.0, probability=0.95)],
                avg_logprob=-0.1,
                no_speech_prob=0.01,
                compression_ratio=1.2,
            )
        ]
        return segments, SimpleNamespace(language="en", duration=10.0), resolved_in

    monkeypatch.setattr(
        "app.services.transcription_pipeline.prepare_cached_audio_for_transcription",
        lambda *args, **kwargs: (source, [], False, True),
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline.get_cached_channel_levels",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.transcription.run_whisper_transcribe",
        fake_run,
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline._apply_recovery_passes",
        lambda **kwargs: (kwargs["base_segments"], 0, 0, [], {}),
    )

    progress_calls: list[tuple[str, float]] = []

    def progress(stage, pct, detail=""):
        progress_calls.append((stage, pct))

    result = run_multipass_transcription(
        resolved=resolved,
        source_audio_path=source,
        temp_dir=tmp_path / "multipass",
        progress=progress,
    )
    assert "secondary_no_vad" in result.skipped_passes
    assert any(stage == "completed" or stage == "merging_transcript" for stage, _ in progress_calls)


def test_cached_audio_reused(tmp_path: Path, monkeypatch):
    from app.services.audio_cache import build_audio_cache_key, store_cached_audio
    from app.services.audio_preprocessing import ChannelMixMode, PreprocessingMode
    from app.services.transcription_config import PREPROCESSING_VERSION

    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")
    cached = tmp_path / "cached.wav"
    cached.write_bytes(b"RIFF....CACHED")
    cache_key = build_audio_cache_key(
        source_path=source,
        mode=PreprocessingMode.ORIGINAL,
        channel_mix=ChannelMixMode.MONO,
        preprocessing_version=PREPROCESSING_VERSION,
    )
    store_cached_audio(cache_key, cached)

    from app.services.audio_cache import prepare_cached_audio_for_transcription

    path, _warnings, _fallback, cache_hit = prepare_cached_audio_for_transcription(
        source,
        temp_dir=tmp_path / "prep",
        mode=PreprocessingMode.ORIGINAL,
        channel_mix=ChannelMixMode.MONO,
        preprocessing_version=PREPROCESSING_VERSION,
    )
    assert cache_hit is True
    assert path.name == "audio.wav"
