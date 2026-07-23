from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ProcessingStatus
from app.services.project_store import load_project, save_project
from app.services.transcription import (
    TranscriptionProcessError,
    TranscriptNotFoundError,
    WhisperModelLoadError,
    load_project_transcript,
    reset_whisper_model_cache,
    transcribe_project_audio,
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


def _mock_whisper_result():
    info = SimpleNamespace(language="en", duration=10.5)
    segments = [
        MockSegment(
            id=0,
            start=0.0,
            end=2.5,
            text=" Hello world",
            words=[
                MockWord(word=" Hello", start=0.0, end=0.8, probability=0.99),
                MockWord(word=" world", start=0.8, end=2.5, probability=0.98),
            ],
        ),
        MockSegment(
            id=1,
            start=2.5,
            end=5.0,
            text=" Testing transcription",
            words=[
                MockWord(word=" Testing", start=2.5, end=3.2, probability=0.97),
                MockWord(word=" transcription", start=3.2, end=5.0, probability=0.96),
            ],
        ),
    ]
    return segments, info


@pytest.fixture(autouse=True)
def reset_transcription_state():
    reset_whisper_model_cache()
    yield
    reset_whisper_model_cache()


def _prepare_extracted_audio(sample_project, temp_backend_dirs):
    project_id = sample_project["project_id"]
    audio_dir = temp_backend_dirs["audio_dir"] / project_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / "audio.wav"
    audio_path.write_bytes(b"RIFF....WAVEfmt ")

    project = load_project(project_id)
    project.audio_extraction_status = ProcessingStatus.COMPLETED
    project.extracted_audio_path = f"{project_id}/audio.wav"
    project.extracted_audio_duration_seconds = 10.5
    save_project(project)
    return audio_path


def _mock_multipass_from_whisper(segments, info):
    from app.services.transcription import iter_whisper_segments
    from app.services.transcription_pipeline import CoverageMetrics, MultipassTranscriptionResult

    transcript_segments = iter_whisper_segments(segments)
    word_count = sum(len(segment.words) for segment in transcript_segments)

    def fake_multipass(resolved, source_audio_path, temp_dir, language=None, progress=None, **_kwargs):
        coverage = CoverageMetrics(
            word_count=word_count,
            segment_count=len(transcript_segments),
            spoken_region_coverage=0.5,
            longest_unexplained_gap=0.0,
            model_used=resolved.model_size,
            audio_variant="primary_no_vad",
            vad_state=False,
            preprocessing_mode="original",
        )
        return MultipassTranscriptionResult(
            segments=transcript_segments,
            language=info.language or "unknown",
            duration=round(info.duration or 0.0, 3),
            warnings=list(resolved.warnings),
            coverage=coverage,
            resolved=resolved,
            passes=[],
        )

    return fake_multipass


def _multipass_patches(segments, info):
    return patch(
        "app.services.transcription.run_multipass_transcription",
        side_effect=_mock_multipass_from_whisper(segments, info),
    )


def test_transcription_success(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    segments, info = _mock_whisper_result()

    with _multipass_patches(segments, info):
        document = transcribe_project_audio(sample_project["project_id"], use_full_quality=True)

    assert document.language == "en"
    assert document.duration == pytest.approx(10.5)
    assert document.segment_count == 2
    assert document.word_count == 4
    assert document.segments[0].words[0].word == "Hello"

    transcript_path = (
        temp_backend_dirs["transcripts_dir"]
        / sample_project["project_id"]
        / "transcript.json"
    )
    assert transcript_path.exists()
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert payload["segment_count"] == 2
    assert payload["segments"][0]["words"][0]["word"] == "Hello"


def test_transcription_missing_audio(sample_project):
    with pytest.raises(Exception) as exc_info:
        transcribe_project_audio(sample_project["project_id"])

    assert "Extracted audio" in str(exc_info.value)


def test_transcription_model_load_failure(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)

    with patch(
        "app.services.transcription.run_multipass_transcription",
        side_effect=WhisperModelLoadError("Failed to load Whisper model 'base'."),
    ):
        with pytest.raises(WhisperModelLoadError):
            transcribe_project_audio(sample_project["project_id"], use_full_quality=True)


def test_transcription_failure_cleans_partial_file(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)

    with patch(
        "app.services.transcription.run_multipass_transcription",
        side_effect=RuntimeError("GPU out of memory"),
    ):
        with pytest.raises(TranscriptionProcessError):
            transcribe_project_audio(sample_project["project_id"], use_full_quality=True)

    transcript_dir = temp_backend_dirs["transcripts_dir"] / sample_project["project_id"]
    assert not (transcript_dir / "transcript.json.part").exists()
    assert not (transcript_dir / "transcript.json").exists()


def test_transcribe_endpoint_updates_project(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    segments, info = _mock_whisper_result()
    client = TestClient(app)

    with _multipass_patches(segments, info):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/transcribe",
            json={"use_full_quality": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["language"] == "en"
    assert body["segment_count"] == 2
    assert body["word_count"] == 4
    assert body["transcript_path"] == f"{sample_project['project_id']}/transcript.json"

    project_response = client.get(f"/api/projects/{sample_project['project_id']}")
    project_body = project_response.json()
    assert project_body["transcription_status"] == "completed"
    assert project_body["detected_language"] == "en"
    assert project_body["transcript_path"] == body["transcript_path"]
    assert project_body["transcription_started_at"] is not None
    assert project_body["transcription_completed_at"] is not None


def test_transcribe_missing_project():
    client = TestClient(app)
    response = client.post("/api/projects/11111111-1111-4111-8111-111111111111/transcribe")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


def test_transcribe_missing_audio_endpoint(sample_project):
    client = TestClient(app)
    response = client.post(f"/api/projects/{sample_project['project_id']}/transcribe")
    assert response.status_code == 404
    assert "Extracted audio" in response.json()["detail"]


def test_transcribe_model_load_failure_endpoint(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    client = TestClient(app)

    with patch(
        "app.services.transcription.run_multipass_transcription",
        side_effect=WhisperModelLoadError("Failed to load Whisper model 'base'."),
    ):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/transcribe",
            json={"use_full_quality": True},
        )

    assert response.status_code == 503
    assert "Failed to load Whisper model" in response.json()["detail"]

    project = load_project(sample_project["project_id"])
    assert project.transcription_status == ProcessingStatus.FAILED
    assert project.last_error is not None


def test_get_transcript_success(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    segments, info = _mock_whisper_result()

    with _multipass_patches(segments, info):
        transcribe_project_audio(sample_project["project_id"], use_full_quality=True)

    document = load_project_transcript(sample_project["project_id"])
    assert document.language == "en"
    assert document.segment_count == 2

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/transcript")
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "en"
    assert body["segment_count"] == 2
    assert len(body["segments"]) == 2


def test_get_transcript_missing(sample_project):
    with pytest.raises(TranscriptNotFoundError):
        load_project_transcript(sample_project["project_id"])

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/transcript")
    assert response.status_code == 404
    assert "Transcript not found" in response.json()["detail"]


def test_get_transcript_missing_project():
    client = TestClient(app)
    response = client.get("/api/projects/11111111-1111-4111-8111-111111111111/transcript")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


CUDA_LIBRARY_ERROR = RuntimeError(
    "Library cublas64_12.dll is not found or cannot be loaded"
)


def test_probe_cuda_usability_false_when_compute_types_unavailable(monkeypatch):
    from app.services.transcription_config import probe_cuda_usability, reset_cuda_availability_cache

    reset_cuda_availability_cache()

    class FakeCT2:
        @staticmethod
        def get_cuda_device_count():
            return 1

        @staticmethod
        def get_supported_compute_types(device):
            return []

    monkeypatch.setitem(__import__("sys").modules, "ctranslate2", FakeCT2())
    assert probe_cuda_usability() is False


def test_load_whisper_model_cuda_init_failure_falls_back_to_cpu():
    from app.services.transcription import _instantiate_whisper_model, reset_whisper_model_cache
    from app.services.transcription_config import (
        ResolvedTranscriptionSettings,
        TranscriptionQualityMode,
        reset_cuda_availability_cache,
    )

    reset_whisper_model_cache()
    reset_cuda_availability_cache()

    cpu_model = SimpleNamespace(name="cpu-model")

    def fake_instantiate(model_size, *, device, compute_type):
        if device == "cuda":
            raise CUDA_LIBRARY_ERROR
        assert device == "cpu"
        assert compute_type == "int8"
        return cpu_model

    resolved = ResolvedTranscriptionSettings(
        mode=TranscriptionQualityMode.BALANCED,
        model_size="base",
        requested_model_size="small",
        device="cuda",
        compute_type="float16",
    )

    with patch(
        "app.services.transcription._instantiate_whisper_model",
        side_effect=fake_instantiate,
    ):
        from app.services.transcription import get_whisper_model_for_settings

        model = get_whisper_model_for_settings(resolved)

    assert model is cpu_model


def test_run_whisper_transcribe_cuda_runtime_failure_falls_back_to_cpu():
    from app.services.transcription import reset_whisper_model_cache, run_whisper_transcribe
    from app.services.transcription_config import (
        ResolvedTranscriptionSettings,
        TranscriptionQualityMode,
        reset_cuda_availability_cache,
    )

    reset_whisper_model_cache()
    reset_cuda_availability_cache()

    info = SimpleNamespace(language="en", duration=2.0)
    cpu_segments = [
        MockSegment(
            id=0,
            start=0.0,
            end=1.0,
            text=" cpu fallback",
            words=[MockWord(word=" cpu", start=0.0, end=1.0, probability=0.9)],
        )
    ]
    cpu_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (cpu_segments, info),
    )
    cuda_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (_ for _ in ()).throw(CUDA_LIBRARY_ERROR),
    )

    def fake_instantiate(model_size, *, device, compute_type):
        if device == "cuda":
            return cuda_model
        return cpu_model

    resolved = ResolvedTranscriptionSettings(
        mode=TranscriptionQualityMode.BALANCED,
        model_size="base",
        requested_model_size="small",
        device="cuda",
        compute_type="float16",
        decode_options={"word_timestamps": True},
    )

    with patch(
        "app.services.transcription._instantiate_whisper_model",
        side_effect=fake_instantiate,
    ):
        segments_iter, returned_info, effective = run_whisper_transcribe(
            resolved,
            "audio.wav",
            word_timestamps=True,
        )

    segments = list(segments_iter)
    assert segments[0].text == " cpu fallback"
    assert returned_info.language == "en"
    assert effective.device == "cpu"
    assert effective.compute_type == "int8"


def test_transcribe_project_audio_after_cuda_runtime_failure(sample_project, temp_backend_dirs):
    from app.services.transcription import reset_whisper_model_cache
    from app.services.transcription_config import reset_cuda_availability_cache

    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    reset_whisper_model_cache()
    reset_cuda_availability_cache()

    info = SimpleNamespace(language="en", duration=10.5)
    cpu_segments, _ = _mock_whisper_result()
    cpu_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (cpu_segments, info),
    )
    cuda_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (_ for _ in ()).throw(CUDA_LIBRARY_ERROR),
    )

    def fake_instantiate(model_size, *, device, compute_type):
        if device == "cuda":
            return cuda_model
        return cpu_model

    with patch(
        "app.services.transcription_pipeline.prepare_cached_audio_for_transcription",
        lambda source_path, temp_dir, mode, channel_mix=None, preprocessing_version=None: (
            source_path,
            [],
            False,
            False,
        ),
    ), patch(
        "app.services.transcription_pipeline.analyze_channel_levels",
        lambda *_args, **_kwargs: [],
    ), patch(
        "app.services.transcription_pipeline._apply_recovery_passes",
        lambda **kwargs: (kwargs["base_segments"], 0, 0, [], {}),
    ), patch(
        "app.services.transcription._instantiate_whisper_model",
        side_effect=fake_instantiate,
    ):
        document = transcribe_project_audio(sample_project["project_id"], use_full_quality=True)

    assert document.language == "en"
    assert document.segment_count == 2
