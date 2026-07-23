from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.project import ProcessingStatus, TranscriptDocument, TranscriptSegment
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import (
    AnalysisNotFoundError,
    AnalysisTranscriptRequiredError,
    analyze_project_timeline,
    load_project_analysis,
)
from app.services.analysis.base import AnalysisProviderError


def _write_completed_transcript(sample_project, temp_backend_dirs, segments: list[TranscriptSegment]):
    project_id = sample_project["project_id"]
    transcript_dir = temp_backend_dirs["transcripts_dir"] / project_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    document = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=max((segment.end for segment in segments), default=0.0),
        segment_count=len(segments),
        word_count=sum(len(segment.words) for segment in segments),
        segments=segments,
    )
    transcript_path = transcript_dir / "transcript.json"
    transcript_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")

    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.transcript_path = f"{project_id}/transcript.json"
    project.detected_language = "en"
    save_project(project)
    return document


@pytest.fixture()
def sample_transcript_segments():
    return [
        TranscriptSegment(
            id=0,
            start=0.0,
            end=2.5,
            text="Wait, that was insane!",
            words=[],
        ),
        TranscriptSegment(
            id=1,
            start=2.5,
            end=5.0,
            text="lol that was actually funny",
            words=[],
        ),
        TranscriptSegment(
            id=2,
            start=5.0,
            end=8.0,
            text="Because this tip helps you learn the mechanic",
            words=[],
        ),
    ]


def test_analyze_success(sample_project, temp_backend_dirs, sample_transcript_segments):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)

    document = analyze_project_timeline(sample_project["project_id"])

    assert document.provider == "heuristic"
    assert document.is_heuristic_fallback is True
    assert document.segment_count == 3
    assert document.clip_candidate_count >= 1
    assert all(0.0 <= segment.excitement_score <= 10.0 for segment in document.segments)
    assert all(segment.reason for segment in document.segments)

    analysis_path = (
        temp_backend_dirs["analysis_dir"]
        / sample_project["project_id"]
        / "analysis.json"
    )
    assert analysis_path.exists()


def test_analyze_missing_transcript(sample_project):
    with pytest.raises(AnalysisTranscriptRequiredError):
        analyze_project_timeline(sample_project["project_id"])


def test_get_analysis_success(sample_project, temp_backend_dirs, sample_transcript_segments):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)
    analyze_project_timeline(sample_project["project_id"])

    document = load_project_analysis(sample_project["project_id"])
    assert document.segment_count == 3

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/analysis")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "heuristic"
    assert len(body["segments"]) == 3


def test_get_analysis_missing(sample_project):
    with pytest.raises(AnalysisNotFoundError):
        load_project_analysis(sample_project["project_id"])

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/analysis")
    assert response.status_code == 404
    assert "Analysis not found" in response.json()["detail"]


def test_analyze_endpoint_updates_project(sample_project, temp_backend_dirs, sample_transcript_segments):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)
    client = TestClient(app)

    response = client.post(f"/api/projects/{sample_project['project_id']}/analyze")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["is_heuristic_fallback"] is True
    assert body["clip_candidate_count"] >= 0

    project = load_project(sample_project["project_id"])
    assert project.analysis_status == ProcessingStatus.COMPLETED
    assert project.analysis_provider == "heuristic"
    assert project.analysis_path == f"{sample_project['project_id']}/analysis.json"


def test_analyze_missing_project():
    client = TestClient(app)
    response = client.post("/api/projects/11111111-1111-4111-8111-111111111111/analyze")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


def test_provider_configuration_failure(sample_project, temp_backend_dirs, sample_transcript_segments, monkeypatch):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)
    monkeypatch.setattr(settings, "analysis_provider", "openai")
    monkeypatch.setattr(settings, "analysis_api_key", "")

    client = TestClient(app)
    response = client.post(f"/api/projects/{sample_project['project_id']}/analyze")
    assert response.status_code == 200
    assert response.json()["provider"] == "heuristic"
    assert response.json()["is_heuristic_fallback"] is True


def test_analyze_batches_segments(sample_project, temp_backend_dirs, monkeypatch):
    segments = [
        TranscriptSegment(id=index, start=float(index), end=float(index + 1), text=f"Segment {index}", words=[])
        for index in range(12)
    ]
    _write_completed_transcript(sample_project, temp_backend_dirs, segments)
    monkeypatch.setattr(settings, "analysis_batch_size", 4)

    document = analyze_project_timeline(sample_project["project_id"])
    assert document.segment_count == 12


def test_analyze_invalid_transcript(sample_project, temp_backend_dirs):
    _write_completed_transcript(sample_project, temp_backend_dirs, [])
    client = TestClient(app)

    response = client.post(f"/api/projects/{sample_project['project_id']}/analyze")
    assert response.status_code == 422
    assert "no segments" in response.json()["detail"].lower()


def test_get_analysis_corrupted_file(sample_project, temp_backend_dirs, sample_transcript_segments):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)
    analyze_project_timeline(sample_project["project_id"])

    analysis_path = (
        temp_backend_dirs["analysis_dir"]
        / sample_project["project_id"]
        / "analysis.json"
    )
    analysis_path.write_text("{not valid json", encoding="utf-8")

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/analysis")
    assert response.status_code == 500
    assert "corrupted" in response.json()["detail"].lower()


def test_analyze_failure_cleans_partial_file(
    sample_project,
    temp_backend_dirs,
    sample_transcript_segments,
    monkeypatch,
):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)

    class FailingProvider:
        provider_name = "failing"
        model_name = "test"

        def analyze_batch(self, segments):
            raise AnalysisProviderError("Provider unavailable for test.")

    monkeypatch.setattr(
        "app.services.analysis_pipeline.resolve_analysis_provider",
        lambda: FailingProvider(),
    )

    client = TestClient(app)
    response = client.post(f"/api/projects/{sample_project['project_id']}/analyze")
    assert response.status_code == 200
    assert response.json()["provider"] == "failing"
    assert response.json()["is_heuristic_fallback"] is False

    analysis_dir = temp_backend_dirs["analysis_dir"] / sample_project["project_id"]
    assert (analysis_dir / "analysis.json").exists()
    assert not (analysis_dir / "analysis.json.part").exists()


def test_failed_reanalysis_preserves_prior_analysis(
    sample_project,
    temp_backend_dirs,
    sample_transcript_segments,
    monkeypatch,
):
    _write_completed_transcript(sample_project, temp_backend_dirs, sample_transcript_segments)
    client = TestClient(app)
    initial = client.post(f"/api/projects/{sample_project['project_id']}/analyze")
    assert initial.status_code == 200
    assert initial.json()["provider"] == "heuristic"

    analysis_path = (
        temp_backend_dirs["analysis_dir"]
        / sample_project["project_id"]
        / "analysis.json"
    )
    original_bytes = analysis_path.read_bytes()

    class FailingProvider:
        provider_name = "openai"
        model_name = "gpt-4o-mini"

        def bind_transcript(self, segments):
            return None

        def analyze_batch(self, segments):
            raise AnalysisProviderError("Provider unavailable for test.")

    monkeypatch.setattr(
        "app.services.analysis_pipeline.resolve_analysis_provider",
        lambda: FailingProvider(),
    )

    client = TestClient(app)
    response = client.post(f"/api/projects/{sample_project['project_id']}/analyze")
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"

    assert analysis_path.exists()
    assert analysis_path.read_bytes() != original_bytes

    preserved = load_project_analysis(sample_project["project_id"])
    assert preserved.provider == "openai"
    assert preserved.is_heuristic_fallback is False

    project = load_project(sample_project["project_id"])
    assert project.analysis_status == ProcessingStatus.COMPLETED
    assert project.analysis_provider == "openai"
