from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    CaptionSegment,
    ProcessingStatus,
    TranscriptSegment,
    TranscriptWord,
    TranscriptionQualityMode,
)
from app.services.audio_preprocessing import (
    AudioPreprocessingError,
    PreprocessingMode,
    _build_preprocessing_command,
    preprocess_with_fallback,
)
from app.services.caption_editing import (
    insert_caption_segment,
    merge_caption_segments,
    split_caption_segment,
)
from app.services.clip_boundary import (
    compute_padded_range,
    filter_segments_to_clip_range,
    remap_segments_to_clip_relative,
    remap_words_to_clip_relative,
)
from app.services.transcription_cache import TranscriptionCacheKey, build_cache_key
from app.services.transcription_config import (
    MODE_CONFIGS,
    resolve_transcription_settings,
    sanitize_vocabulary_hints,
)
from app.services.transcription_quality import (
    analyze_transcription_quality,
    merge_transcript_segments,
    merge_words_without_duplicates,
)
from app.services.transcription import reset_whisper_model_cache
from app.services.transcription_pipeline import CoverageMetrics, MultipassTranscriptionResult


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


def _completed_process(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def reset_state():
    reset_whisper_model_cache()
    yield
    reset_whisper_model_cache()


def test_quality_mode_configs():
    assert TranscriptionQualityMode.FAST in MODE_CONFIGS
    assert TranscriptionQualityMode.BALANCED in MODE_CONFIGS
    assert TranscriptionQualityMode.HIGH_ACCURACY in MODE_CONFIGS
    assert MODE_CONFIGS[TranscriptionQualityMode.FAST].beam_size == 1
    assert MODE_CONFIGS[TranscriptionQualityMode.BALANCED].beam_size == 5
    assert MODE_CONFIGS[TranscriptionQualityMode.HIGH_ACCURACY].beam_size == 10


def test_resolve_transcription_settings_cpu_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.transcription_config.detect_device",
        lambda: ("cpu", "int8", []),
    )
    resolved = resolve_transcription_settings(quality_mode="balanced")
    assert resolved.device == "cpu"
    assert resolved.compute_type == "int8"
    assert resolved.decode_options["word_timestamps"] is True


def test_unavailable_model_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.transcription_config.settings.whisper_model_size",
        "base",
    )
    config = MODE_CONFIGS[TranscriptionQualityMode.HIGH_ACCURACY]
    model, warnings = __import__(
        "app.services.transcription_config",
        fromlist=["resolve_model_for_mode"],
    ).resolve_model_for_mode(
        type(
            "Cfg",
            (),
            {
                "model_candidates": ("nonexistent-model",),
            },
        )()
    )
    assert model == "base"
    assert warnings


def test_preprocessing_command_original_has_no_filters():
    command = _build_preprocessing_command(
        Path("in.wav"),
        Path("out.wav"),
        mode=PreprocessingMode.ORIGINAL,
    )
    assert "-af" not in command
    assert "16000" in command


def test_preprocessing_command_normalized_contains_loudnorm():
    command = _build_preprocessing_command(
        Path("in.wav"),
        Path("out.wav"),
        mode=PreprocessingMode.NORMALIZED,
    )
    assert "-af" in command
    assert "loudnorm" in command[command.index("-af") + 1]


def test_preprocessing_failure_fallback(tmp_path, monkeypatch):
    source = tmp_path / "audio.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(
        "app.services.audio_preprocessing.prepare_audio_variant",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AudioPreprocessingError("ffmpeg failed")
        ),
    )
    output, warnings, used_fallback = preprocess_with_fallback(source, temp_dir=tmp_path / "t")
    assert output == source
    assert used_fallback is True
    assert warnings


def test_clip_boundary_padding_clamped():
    padded = compute_padded_range(0.2, 1.0, source_duration=1.0, padding_seconds=0.75)
    assert padded.padded_start == 0.0
    assert padded.padded_end == 1.0


def test_remap_words_speech_at_clip_start():
    words = [TranscriptWord(word="Hello", start=1.0, end=1.5, probability=0.9)]
    relative = remap_words_to_clip_relative(words, clip_start=1.0, clip_end=4.0)
    assert relative[0].start == 0.0


def test_remap_words_speech_at_clip_end():
    words = [TranscriptWord(word="Bye", start=3.5, end=4.0, probability=0.9)]
    relative = remap_words_to_clip_relative(words, clip_start=1.0, clip_end=4.0)
    assert relative[0].end == 3.0


def test_filter_words_outside_clip_range():
    words = [
        TranscriptWord(word="Before", start=0.0, end=0.5, probability=0.9),
        TranscriptWord(word="Inside", start=1.5, end=2.0, probability=0.9),
        TranscriptWord(word="After", start=4.5, end=5.0, probability=0.9),
    ]
    filtered = remap_words_to_clip_relative(words, clip_start=1.0, clip_end=4.0)
    assert len(filtered) == 1
    assert filtered[0].word == "Inside"


def test_no_negative_or_past_duration_timestamps():
    segments = [
        TranscriptSegment(
            id=0,
            start=0.5,
            end=1.5,
            text="clip start",
            words=[TranscriptWord(word="clip", start=0.5, end=1.0, probability=0.9)],
        )
    ]
    relative = remap_segments_to_clip_relative(segments, clip_start=0.5, clip_end=2.0)
    assert all(segment.start >= 0 for segment in relative)
    assert all(segment.end <= 1.5 + 0.001 for segment in relative)


def test_suspicious_gap_detection():
    segments = [
        TranscriptSegment(id=0, start=0.0, end=1.0, text="one", words=[]),
        TranscriptSegment(id=1, start=3.0, end=4.0, text="two", words=[]),
    ]
    quality = analyze_transcription_quality(segments, duration=4.0)
    assert quality.rating.value in {"review_recommended", "poor"}
    assert any("missing speech" in warning.lower() for warning in quality.warnings)


def test_merge_prevents_duplicate_segments():
    primary = [TranscriptSegment(id=0, start=0.0, end=1.0, text="hello", words=[])]
    recovered = [TranscriptSegment(id=0, start=0.0, end=1.0, text="hello", words=[])]
    merged = merge_transcript_segments(primary, recovered, replace_start=0.0, replace_end=1.0)
    assert len(merged) == 1


def test_merge_words_without_duplicates():
    existing = [TranscriptWord(word="hello", start=0.0, end=0.5, probability=0.9)]
    recovered = [TranscriptWord(word="hello", start=0.0, end=0.5, probability=0.95)]
    merged = merge_words_without_duplicates(existing, recovered)
    assert len(merged) == 1


def test_vocabulary_hints_sanitized():
    assert sanitize_vocabulary_hints("  Alice   Bob  ") == "Alice Bob"
    assert sanitize_vocabulary_hints("x" * 600) is not None
    assert len(sanitize_vocabulary_hints("x" * 600) or "") <= 500


def test_manual_insert_and_split_segment():
    segments = [
        CaptionSegment(
            id="seg-1",
            text="hello world",
            start=0.0,
            end=2.0,
            words=[
                __import__("app.models.project", fromlist=["CaptionWord"]).CaptionWord(
                    word="hello", start=0.0, end=1.0
                ),
                __import__("app.models.project", fromlist=["CaptionWord"]).CaptionWord(
                    word="world", start=1.0, end=2.0
                ),
            ],
            sequence=0,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
    ]
    split = split_caption_segment(
        segments,
        segment_id="seg-1",
        split_time=1.0,
        clip_duration=5.0,
    )
    assert len(split) == 2
    inserted = insert_caption_segment(
        split,
        text="missing",
        start=2.5,
        end=3.0,
        clip_duration=5.0,
    )
    assert len(inserted) == 3


def test_merge_segments():
    segments = [
        CaptionSegment(
            id="a",
            text="one",
            start=0.0,
            end=1.0,
            words=[],
            sequence=0,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
        CaptionSegment(
            id="b",
            text="two",
            start=1.0,
            end=2.0,
            words=[],
            sequence=1,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    ]
    merged = merge_caption_segments(
        segments,
        first_segment_id="a",
        second_segment_id="b",
        clip_duration=5.0,
    )
    assert len(merged) == 1


def test_cache_key_changes_with_settings(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"abc")
    key_a = build_cache_key(
        audio_path=audio,
        quality_mode=TranscriptionQualityMode.FAST,
        model_size="base",
    )
    key_b = build_cache_key(
        audio_path=audio,
        quality_mode=TranscriptionQualityMode.HIGH_ACCURACY,
        model_size="medium",
    )
    assert key_a.digest() != key_b.digest()


def test_transcribe_with_quality_mode_endpoint(sample_project, temp_backend_dirs):
    from app.services.project_store import load_project, save_project

    project_id = sample_project["project_id"]
    audio_dir = temp_backend_dirs["audio_dir"] / project_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "audio.wav").write_bytes(b"RIFF....WAVEfmt ")
    project = load_project(project_id)
    project.audio_extraction_status = ProcessingStatus.COMPLETED
    project.extracted_audio_path = f"{project_id}/audio.wav"
    save_project(project)

    info = SimpleNamespace(language="en", duration=10.5)
    segments = [
        MockSegment(
            id=0,
            start=0.0,
            end=2.0,
            text=" hello",
            words=[MockWord(word=" hello", start=0.0, end=2.0, probability=0.9)],
        )
    ]
    client = TestClient(app)

    def fake_multipass(resolved, source_audio_path, temp_dir, language=None, progress=None, **_kwargs):
        transcript_segments = __import__(
            "app.services.transcription",
            fromlist=["iter_whisper_segments"],
        ).iter_whisper_segments(segments)
        return MultipassTranscriptionResult(
            segments=transcript_segments,
            language=info.language,
            duration=info.duration,
            warnings=[],
            coverage=CoverageMetrics(
                word_count=1,
                segment_count=1,
                spoken_region_coverage=0.5,
                longest_unexplained_gap=0.0,
            ),
            resolved=resolved,
            passes=[],
        )

    with patch(
        "app.services.transcription.run_multipass_transcription",
        side_effect=fake_multipass,
    ):
        response = client.post(
            f"/api/projects/{project_id}/transcribe",
            json={
                "quality_mode": "high_accuracy",
                "vocabulary_hints": "AcmeCorp",
                "use_full_quality": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["quality_mode"] == "high_accuracy"
