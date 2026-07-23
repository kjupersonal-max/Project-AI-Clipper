from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.project import TranscriptSegment, TranscriptTier, TranscriptionQualityMode
from app.services.discovery_transcription import (
    deduplicate_overlap_segments,
    merge_chunk_segments,
    plan_audio_chunks,
)
from app.services.transcription_config import (
    DISCOVERY_MODE_CONFIG,
    resolve_discovery_model,
    resolve_discovery_settings,
)


def test_discovery_mode_uses_fast_decoding_settings():
    settings = resolve_discovery_settings(language="en")
    assert settings.model_size == "tiny.en"
    assert settings.decode_options["beam_size"] == 1
    assert settings.decode_options["best_of"] == 1
    assert settings.decode_options["temperature"] == [0.0]
    assert settings.decode_options["vad_filter"] is False
    assert settings.decode_options["word_timestamps"] is False
    assert settings.recovery_options == {}


def test_discovery_model_falls_back_to_base_for_non_english():
    assert resolve_discovery_model("es") == "tiny"
    assert resolve_discovery_model(None) == "tiny"


def test_discovery_config_has_no_temperature_fallback_sequence():
    assert DISCOVERY_MODE_CONFIG.temperature == (0.0,)


def test_plan_audio_chunks_for_short_video_is_single_chunk():
    chunks = plan_audio_chunks(duration=500.0, chunk_seconds=1200.0, overlap_seconds=10.0)
    assert len(chunks) == 1
    assert chunks[0].start == 0.0
    assert chunks[0].end == 500.0


def test_plan_audio_chunks_for_twenty_minute_video_is_single_chunk():
    chunks = plan_audio_chunks(duration=1200.0, chunk_seconds=1200.0, overlap_seconds=10.0)
    assert len(chunks) == 1


def test_plan_audio_chunks_for_long_video():
    chunks = plan_audio_chunks(duration=3600.0, chunk_seconds=600.0, overlap_seconds=10.0)
    assert len(chunks) >= 6
    assert chunks[0].start == 0.0
    assert chunks[-1].end == 3600.0


def test_overlap_deduplication_removes_duplicate_text():
    left = [
        TranscriptSegment(id=0, start=590.0, end=595.0, text="hello there"),
    ]
    right = [
        TranscriptSegment(id=0, start=590.0, end=595.0, text="hello there"),
        TranscriptSegment(id=1, start=595.0, end=600.0, text="new content"),
    ]
    deduped = deduplicate_overlap_segments(left, right, overlap_start=590.0, overlap_end=600.0)
    assert len(deduped) == 1
    assert deduped[0].text == "new content"


def test_merge_chunk_segments_reindexes_ids():
    from app.services.discovery_transcription import AudioChunkPlan

    first = [TranscriptSegment(id=0, start=0.0, end=1.0, text="a")]
    second = [TranscriptSegment(id=0, start=1.0, end=2.0, text="b")]
    plans = [AudioChunkPlan(index=0, start=0.0, end=60.0), AudioChunkPlan(index=1, start=55.0, end=120.0)]
    merged = merge_chunk_segments([first, second], chunk_plans=plans, overlap_seconds=5.0)
    assert [segment.id for segment in merged] == [0, 1]


@patch("app.services.discovery_transcription.transcribe_audio_to_segments")
@patch("app.services.discovery_transcription.extract_audio_chunk_from_wav")
@patch("app.services.discovery_transcription.get_whisper_model_for_settings")
@patch("app.services.discovery_transcription.locate_project_audio")
@patch("app.services.discovery_transcription.load_project")
@patch("app.services.discovery_transcription.save_project")
def test_run_discovery_transcription_stores_discovery_tier(
    mock_save,
    mock_load_project,
    mock_locate_audio,
    mock_get_model,
    mock_extract_chunk,
    mock_transcribe,
    temp_backend_dirs,
    sample_project,
):
    project_id = sample_project["project_id"]
    audio_path = temp_backend_dirs["audio_dir"] / project_id / "audio.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"\x00" * 32000)
    mock_locate_audio.return_value = audio_path
    mock_load_project.return_value = sample_project["project"]

    mock_get_model.return_value = object()
    resolved = resolve_discovery_settings(language="en")
    info = SimpleNamespace(duration=10.0, language="en")
    mock_transcribe.return_value = (
        [TranscriptSegment(id=0, start=0.0, end=1.0, text="hello", words=[])],
        info,
        resolved,
        object(),
    )

    from app.services.discovery_transcription import run_discovery_transcription

    document = run_discovery_transcription(project_id, language="en", use_cache=False)
    assert document.transcript_tier == TranscriptTier.DISCOVERY
    assert document.quality_mode == TranscriptionQualityMode.FAST


@patch("app.services.transcription.run_multipass_transcription")
@patch("app.services.transcription.locate_project_audio")
@patch("app.services.transcription.load_project")
def test_manual_full_quality_transcription_still_works(
    mock_load_project,
    mock_locate_audio,
    mock_multipass,
    temp_backend_dirs,
    sample_project,
):
    project_id = sample_project["project_id"]
    audio_path = temp_backend_dirs["audio_dir"] / project_id / "audio.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"\x00" * 32000)
    mock_locate_audio.return_value = audio_path
    mock_load_project.return_value = sample_project["project"]

    from app.services.transcription_pipeline import MultipassTranscriptionResult
    from app.services.transcription_config import resolve_transcription_settings
    from app.services.transcription import transcribe_project_audio

    resolved = resolve_transcription_settings(quality_mode="balanced")
    mock_multipass.return_value = MultipassTranscriptionResult(
        segments=[TranscriptSegment(id=0, start=0.0, end=1.0, text="hello", words=[])],
        language="en",
        duration=10.0,
        warnings=[],
        coverage=None,
        resolved=resolved,
    )

    document = transcribe_project_audio(project_id, quality_mode="balanced", use_full_quality=True, use_cache=False)
    assert document.transcript_tier == TranscriptTier.FULL_QUALITY


def test_build_cache_key_includes_transcript_tier(tmp_path):
    from pathlib import Path

    from app.services.transcription_cache import build_cache_key

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"test")
    key = build_cache_key(
        audio_path=audio_path,
        model_size="base.en",
        transcript_tier=TranscriptTier.DISCOVERY,
        chunk_index=2,
        clip_start=600.0,
        clip_end=1200.0,
    )
    assert key.transcript_tier == TranscriptTier.DISCOVERY
    assert key.chunk_index == 2
