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


def test_transcription_success(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    segments, info = _mock_whisper_result()

    mock_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (segments, info),
    )

    with patch(
        "app.services.transcription.get_whisper_model",
        return_value=mock_model,
    ):
        document = transcribe_project_audio(sample_project["project_id"])

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
        "app.services.transcription.get_whisper_model",
        side_effect=WhisperModelLoadError("Failed to load Whisper model 'base'."),
    ):
        with pytest.raises(WhisperModelLoadError):
            transcribe_project_audio(sample_project["project_id"])


def test_transcription_failure_cleans_partial_file(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)

    def failing_transcribe(*_args, **_kwargs):
        raise RuntimeError("GPU out of memory")

    mock_model = SimpleNamespace(transcribe=failing_transcribe)

    with patch(
        "app.services.transcription.get_whisper_model",
        return_value=mock_model,
    ):
        with pytest.raises(TranscriptionProcessError):
            transcribe_project_audio(sample_project["project_id"])

    transcript_dir = temp_backend_dirs["transcripts_dir"] / sample_project["project_id"]
    assert not (transcript_dir / "transcript.json.part").exists()
    assert not (transcript_dir / "transcript.json").exists()


def test_transcribe_endpoint_updates_project(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    segments, info = _mock_whisper_result()
    mock_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (segments, info),
    )
    client = TestClient(app)

    with patch(
        "app.services.transcription.get_whisper_model",
        return_value=mock_model,
    ):
        response = client.post(f"/api/projects/{sample_project['project_id']}/transcribe")

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
        "app.services.transcription.get_whisper_model",
        side_effect=WhisperModelLoadError("Failed to load Whisper model 'base'."),
    ):
        response = client.post(f"/api/projects/{sample_project['project_id']}/transcribe")

    assert response.status_code == 503
    assert "Failed to load Whisper model" in response.json()["detail"]

    project = load_project(sample_project["project_id"])
    assert project.transcription_status == ProcessingStatus.FAILED
    assert project.last_error is not None


def test_get_transcript_success(sample_project, temp_backend_dirs):
    _prepare_extracted_audio(sample_project, temp_backend_dirs)
    segments, info = _mock_whisper_result()
    mock_model = SimpleNamespace(
        transcribe=lambda *_args, **_kwargs: (segments, info),
    )

    with patch(
        "app.services.transcription.get_whisper_model",
        return_value=mock_model,
    ):
        transcribe_project_audio(sample_project["project_id"])

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
