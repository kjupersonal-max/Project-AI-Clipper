from __future__ import annotations

import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.project import TranscriptSegment, TranscriptWord, TranscriptionQualityMode
from app.services.audio_energy import (
    EnergyWindow,
    analyze_audio_energy,
    find_possible_speech_without_transcript,
)
from app.services.audio_preprocessing import (
    ChannelMixMode,
    PreprocessingMode,
    _build_preprocessing_command,
    _mode_filter,
)
from app.services.transcription import iter_whisper_segments
from app.services.transcription_config import (
    CONSERVATIVE_VAD_PARAMETERS,
    MODE_CONFIGS,
    ResolvedTranscriptionSettings,
    build_decode_options,
    resolve_transcription_settings,
)
from app.services.transcription_pipeline import (
    CoverageMetrics,
    MultipassTranscriptionResult,
    TranscriptionPassResult,
    _compare_vad_vs_no_vad,
    _select_best_channel_audio,
    run_multipass_transcription,
)


@dataclass
class MockWord:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class MockSegment:
    id: int
    start: float
    end: float
    text: str
    words: list[MockWord]
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None


def _pass_result(
    *,
    variant: str,
    segments: list[TranscriptSegment],
    word_count: int,
    duration: float = 10.0,
    vad_enabled: bool = False,
    preprocessing_mode: str = "original",
) -> TranscriptionPassResult:
    return TranscriptionPassResult(
        variant=variant,
        segments=segments,
        language="en",
        duration=duration,
        word_count=word_count,
        text=" ".join(segment.text for segment in segments),
        model="small",
        requested_model="small",
        device="cpu",
        compute_type="int8",
        preprocessing_mode=preprocessing_mode,
        channel_mix="mono",
        vad_enabled=vad_enabled,
        vad_parameters=CONSERVATIVE_VAD_PARAMETERS if vad_enabled else None,
        coverage=CoverageMetrics(
            word_count=word_count,
            segment_count=len(segments),
            spoken_region_coverage=0.5,
            longest_unexplained_gap=0.0,
            model_used="small",
            audio_variant=variant,
            vad_state=vad_enabled,
            preprocessing_mode=preprocessing_mode,
        ),
    )


def _make_wav_with_loud_region(path: Path) -> None:
    sample_rate = 16000
    quiet = [100] * int(sample_rate * 0.5)
    loud = [9000] * int(sample_rate * 2.5)
    samples = quiet + loud
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_balanced_mode_does_not_enable_vad_by_default():
    config = MODE_CONFIGS[TranscriptionQualityMode.BALANCED]
    assert config.vad_filter is False
    assert config.use_vad_recovery_pass is False
    assert config.primary_preprocessing == PreprocessingMode.ORIGINAL
    assert config.secondary_preprocessing == PreprocessingMode.NORMALIZED


def test_high_accuracy_uses_vad_only_as_recovery_pass():
    config = MODE_CONFIGS[TranscriptionQualityMode.HIGH_ACCURACY]
    assert config.vad_filter is False
    assert config.use_vad_recovery_pass is True


def test_default_balanced_does_not_force_speech_filtering():
    resolved = resolve_transcription_settings(quality_mode="balanced")
    assert resolved.primary_preprocessing == PreprocessingMode.ORIGINAL
    assert resolved.decode_options["vad_filter"] is False


def test_preprocessing_variants_are_separate():
    assert _mode_filter(PreprocessingMode.ORIGINAL) is None
    assert "loudnorm" in (_mode_filter(PreprocessingMode.NORMALIZED) or "")
    assert "highpass" in (_mode_filter(PreprocessingMode.SPEECH_FILTERED) or "")

    original_cmd = _build_preprocessing_command(
        Path("in.wav"),
        Path("out.wav"),
        mode=PreprocessingMode.ORIGINAL,
    )
    normalized_cmd = _build_preprocessing_command(
        Path("in.wav"),
        Path("out.wav"),
        mode=PreprocessingMode.NORMALIZED,
    )
    filtered_cmd = _build_preprocessing_command(
        Path("in.wav"),
        Path("out.wav"),
        mode=PreprocessingMode.SPEECH_FILTERED,
    )
    assert "-af" not in original_cmd
    assert "loudnorm" in normalized_cmd[normalized_cmd.index("-af") + 1]
    assert "highpass" in filtered_cmd[filtered_cmd.index("-af") + 1]


def test_vad_output_with_fewer_words_triggers_non_vad_preference():
    no_vad = _pass_result(
        variant="primary_no_vad",
        segments=[TranscriptSegment(id=0, start=0.0, end=1.0, text="one two three", words=[])],
        word_count=10,
    )
    with_vad = _pass_result(
        variant="primary_vad",
        segments=[TranscriptSegment(id=0, start=0.0, end=1.0, text="one", words=[])],
        word_count=3,
        vad_enabled=True,
    )
    selected, warnings = _compare_vad_vs_no_vad(no_vad, with_vad)
    assert selected is no_vad
    assert any("VAD removed possible speech" in warning for warning in warnings)


def test_empty_vad_transcript_recovery_prefers_non_vad():
    no_vad = _pass_result(
        variant="primary_no_vad",
        segments=[TranscriptSegment(id=0, start=0.0, end=2.0, text="hello world", words=[])],
        word_count=2,
    )
    with_vad = _pass_result(
        variant="primary_vad",
        segments=[],
        word_count=0,
        vad_enabled=True,
    )
    selected, warnings = _compare_vad_vs_no_vad(no_vad, with_vad)
    assert selected is no_vad
    assert warnings


def test_language_lock_is_passed_to_decode_options():
    resolved = resolve_transcription_settings(quality_mode="balanced", language="en")
    assert resolved.decode_options.get("language") == "en"


def test_model_fallback_warning():
    from app.services.transcription_config import resolve_model_for_mode

    model, warnings = resolve_model_for_mode(
        type("Cfg", (), {"model_candidates": ("nonexistent-model",)})()
    )
    assert model
    assert warnings


def test_energy_gap_triggers_possible_speech_detection():
    energy = [
        EnergyWindow(start=0.0, end=0.25, rms=0.002),
        EnergyWindow(start=0.25, end=0.5, rms=0.002),
        EnergyWindow(start=0.5, end=0.75, rms=0.05),
        EnergyWindow(start=0.75, end=1.0, rms=0.06),
        EnergyWindow(start=1.0, end=1.25, rms=0.05),
    ]
    regions = find_possible_speech_without_transcript(
        energy,
        segments=[TranscriptSegment(id=0, start=0.0, end=0.5, text="hi", words=[])],
    )
    assert regions
    assert regions[0].start >= 0.5


def test_truly_silent_region_does_not_trigger_recovery(tmp_path: Path):
    wav_path = tmp_path / "silent.wav"
    sample_rate = 16000
    frame_count = int(sample_rate * 2.0)
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack(f"<{frame_count}h", *([0] * frame_count)))
    energy = analyze_audio_energy(wav_path, window_seconds=0.25)
    regions = find_possible_speech_without_transcript(energy, segments=[])
    assert not regions


def test_multipass_balanced_runs_without_vad_primary(tmp_path: Path, monkeypatch):
    source = tmp_path / "audio.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")
    resolved = resolve_transcription_settings(quality_mode="balanced")
    calls: list[bool] = []

    segments = [
        MockSegment(
            id=0,
            start=0.0,
            end=1.0,
            text=" hello",
            words=[MockWord(word=" hello", start=0.0, end=1.0, probability=0.9)],
        )
    ]
    info = SimpleNamespace(language="en", duration=1.0)

    def fake_run(resolved_in, audio_path, **options):
        calls.append(options.get("vad_filter", False))
        return segments, info, resolved_in

    monkeypatch.setattr(
        "app.services.transcription_pipeline.prepare_cached_audio_for_transcription",
        lambda source_path, temp_dir, mode, channel_mix=ChannelMixMode.MONO, preprocessing_version=None: (
            source_path,
            [],
            False,
            False,
        ),
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline.get_cached_channel_levels",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline.analyze_channel_levels",
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

    monkeypatch.setattr(
        "app.services.transcription_pipeline._apply_recovery_passes",
        lambda **kwargs: (kwargs["base_segments"], 0, 0, [], {}),
    )

    result = run_multipass_transcription(
        resolved=resolved,
        source_audio_path=source,
        temp_dir=tmp_path / "multipass",
    )
    assert calls
    assert calls[0] is False


def test_multipass_high_accuracy_compares_vad_pass(tmp_path: Path, monkeypatch):
    source = tmp_path / "audio.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")
    resolved = resolve_transcription_settings(quality_mode="high_accuracy")
    vad_calls: list[bool] = []

    def fake_run(resolved_in, audio_path, **options):
        vad_calls.append(options.get("vad_filter", False))
        if options.get("vad_filter"):
            segments = [
                MockSegment(
                    id=0,
                    start=0.0,
                    end=1.0,
                    text=" one",
                    words=[MockWord(word=" one", start=0.0, end=1.0, probability=0.9)],
                )
            ]
        else:
            segments = [
                MockSegment(
                    id=0,
                    start=0.0,
                    end=2.0,
                    text=" one two three four",
                    words=[
                        MockWord(word=" one", start=0.0, end=0.5, probability=0.9),
                        MockWord(word=" two", start=0.5, end=1.0, probability=0.9),
                        MockWord(word=" three", start=1.0, end=1.5, probability=0.9),
                        MockWord(word=" four", start=1.5, end=2.0, probability=0.9),
                    ],
                )
            ]
        return segments, SimpleNamespace(language="en", duration=30.0), resolved_in

    monkeypatch.setattr(
        "app.services.transcription_pipeline.prepare_cached_audio_for_transcription",
        lambda source_path, temp_dir, mode, channel_mix=ChannelMixMode.MONO, preprocessing_version=None: (
            source_path,
            [],
            False,
            False,
        ),
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline.get_cached_channel_levels",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline.analyze_channel_levels",
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

    result = run_multipass_transcription(
        resolved=resolved,
        source_audio_path=source,
        temp_dir=tmp_path / "multipass",
    )
    assert True in vad_calls
    assert any("VAD removed possible speech" in warning for warning in result.warnings)


def test_stereo_channel_imbalance_prefers_louder_channel(tmp_path: Path, monkeypatch):
    source = tmp_path / "stereo.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")

    from app.services.audio_preprocessing import ChannelLevelDiagnostics

    monkeypatch.setattr(
        "app.services.transcription_pipeline.get_cached_channel_levels",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.transcription_pipeline.analyze_channel_levels",
        lambda *_args, **_kwargs: [
            ChannelLevelDiagnostics(channel="left", peak_amplitude=0.2, rms_level=0.05),
            ChannelLevelDiagnostics(channel="right", peak_amplitude=0.8, rms_level=0.2),
        ],
    )
    selected_mix: list[ChannelMixMode] = []

    def fake_prepare(source_path, temp_dir, mode, channel_mix=ChannelMixMode.MONO, preprocessing_version=None):
        selected_mix.append(channel_mix)
        return source_path, [], False, False

    monkeypatch.setattr(
        "app.services.transcription_pipeline.prepare_cached_audio_for_transcription",
        fake_prepare,
    )

    audio_path, mix, warnings = _select_best_channel_audio(
        source,
        tmp_path / "channel",
        mode=PreprocessingMode.ORIGINAL,
    )
    assert audio_path == source
    assert mix == ChannelMixMode.RIGHT
    assert any("Stereo imbalance detected" in warning for warning in warnings)
    assert selected_mix[0] == ChannelMixMode.RIGHT


def test_conservative_vad_parameters_are_less_aggressive():
    assert CONSERVATIVE_VAD_PARAMETERS["threshold"] < 0.5
    assert CONSERVATIVE_VAD_PARAMETERS["min_speech_duration_ms"] <= 100


def test_build_decode_options_respects_vad_override():
    config = MODE_CONFIGS[TranscriptionQualityMode.BALANCED]
    options = build_decode_options(mode_config=config, vad_filter=True)
    assert options["vad_filter"] is True
    assert options["vad_parameters"] == CONSERVATIVE_VAD_PARAMETERS
