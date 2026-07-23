from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.project import ProcessingStatus, TranscriptDocument, TranscriptSegment, TranscriptTier
from app.services.clip_selection import invalidate_stale_clip_candidates, load_project_clip_candidates
from app.services.project_store import load_project, save_project


def _write_discovery_transcript(sample_project, temp_backend_dirs, segments: list[TranscriptSegment]) -> None:
    project_id = sample_project["project_id"]
    transcript_dir = temp_backend_dirs["transcripts_dir"] / project_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    document = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=max((segment.end for segment in segments), default=0.0),
        segment_count=len(segments),
        word_count=0,
        segments=segments,
    )
    discovery_path = transcript_dir / "discovery_transcript.json"
    discovery_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")
    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.discovery_transcript_path = f"{project_id}/discovery_transcript.json"
    project.transcript_path = f"{project_id}/discovery_transcript.json"
    save_project(project)


def _long_segments(count: int = 40) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    phrases = [
        "Wait, that was insane!",
        "Because this tip helps you learn fast",
        "No way, that clutch was crazy!",
        "lol that was actually funny",
    ]
    for index in range(count):
        start = cursor
        end = start + 4.0
        segments.append(
            TranscriptSegment(
                id=index,
                start=start,
                end=end,
                text=phrases[index % len(phrases)],
                words=[],
            )
        )
        cursor = end + 0.2
    return segments


def test_ui_workflow_returns_bounded_quality_clips(sample_project, temp_backend_dirs):
    client = TestClient(app)
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments())

    with patch("app.services.discovery_transcription.run_discovery_transcription") as mock_discovery:
        mock_discovery.return_value = TranscriptDocument(
            project_id=project_id,
            language="en",
            duration=170.0,
            segment_count=40,
            word_count=0,
            segments=_long_segments(),
        )
        transcribe = client.post(f"/api/projects/{project_id}/transcribe")
    assert transcribe.status_code == 200

    analyze = client.post(f"/api/projects/{project_id}/analyze")
    assert analyze.status_code == 200

    select = client.post(f"/api/projects/{project_id}/select-clips", json={})
    assert select.status_code == 200
    assert 0 < select.json()["candidate_count"] <= settings.clip_selection_hard_max_candidates

    candidates = client.get(f"/api/projects/{project_id}/clip-candidates")
    assert candidates.status_code == 200
    payload = candidates.json()
    assert payload["selection_pipeline_version"] == settings.clip_selection_pipeline_version
    assert 0 < payload["candidate_count"] <= settings.clip_selection_hard_max_candidates
    for candidate in payload["candidates"]:
        assert candidate["duration"] >= 15.0


def test_api_transcribe_uses_discovery_path_with_language_hint(sample_project, temp_backend_dirs):
    client = TestClient(app)
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments(8))

    with patch("app.services.discovery_transcription.run_discovery_transcription") as mock_discovery:
        mock_discovery.return_value = TranscriptDocument(
            project_id=project_id,
            language="en",
            duration=40.0,
            segment_count=8,
            word_count=0,
            segments=_long_segments(8),
            transcript_tier=TranscriptTier.DISCOVERY,
        )
        response = client.post(f"/api/projects/{project_id}/transcribe")

    assert response.status_code == 200
    mock_discovery.assert_called_once()
    _, kwargs = mock_discovery.call_args
    assert kwargs.get("language") == "en"
    assert response.json()["transcript_tier"] == "discovery"


def test_rerun_selection_replaces_candidates_not_appends(sample_project, temp_backend_dirs):
    client = TestClient(app)
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments(20))

    assert client.post(f"/api/projects/{project_id}/analyze").status_code == 200
    assert client.post(f"/api/projects/{project_id}/select-clips", json={}).status_code == 200
    first = client.get(f"/api/projects/{project_id}/clip-candidates").json()
    first_ids = {candidate["clip_id"] for candidate in first["candidates"]}

    assert client.post(f"/api/projects/{project_id}/select-clips", json={}).status_code == 200
    second = client.get(f"/api/projects/{project_id}/clip-candidates").json()
    assert second["candidate_count"] <= settings.clip_selection_hard_max_candidates
    assert len(second["candidates"]) == second["candidate_count"]


def test_stale_candidates_are_invalidated(sample_project, temp_backend_dirs):
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments(12))
    client = TestClient(app)
    assert client.post(f"/api/projects/{project_id}/analyze").status_code == 200
    assert client.post(f"/api/projects/{project_id}/select-clips", json={}).status_code == 200

    path = temp_backend_dirs["clip_candidates_dir"] / project_id / "clip_candidates.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selection_pipeline_version"] = "legacy-v0"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert invalidate_stale_clip_candidates(project_id) is True
    with pytest.raises(Exception):
        load_project_clip_candidates(project_id)


def test_export_rejects_sub_fifteen_second_clip(sample_project, temp_backend_dirs):
    from app.services.clip_export import ClipExportValidationError, _validate_export_times

    with pytest.raises(ClipExportValidationError, match="15"):
        _validate_export_times(start_time=1.0, end_time=5.0, source_duration=120.0)


def test_many_transcript_segments_do_not_produce_many_final_clips(sample_project, temp_backend_dirs):
    client = TestClient(app)
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments(294))
    assert client.post(f"/api/projects/{project_id}/analyze").status_code == 200
    select = client.post(f"/api/projects/{project_id}/select-clips", json={})
    assert select.status_code == 200
    assert select.json()["candidate_count"] <= settings.clip_selection_hard_max_candidates


def test_candidate_captions_generate_without_export(sample_project, temp_backend_dirs):
    client = TestClient(app)
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments(40))

    assert client.post(f"/api/projects/{project_id}/analyze").status_code == 200
    assert client.post(f"/api/projects/{project_id}/select-clips", json={}).status_code == 200

    candidates = client.get(f"/api/projects/{project_id}/clip-candidates").json()
    assert candidates["candidates"]
    candidate = candidates["candidates"][0]
    candidate_id = candidate["clip_id"]
    assert candidate["duration"] >= 15.0

    generate = client.post(
        f"/api/projects/{project_id}/clips/{candidate_id}/captions/generate",
    )
    assert generate.status_code == 200, generate.text
    payload = generate.json()
    assert payload["candidate_id"] == candidate_id
    assert payload["duration"] == pytest.approx(candidate["duration"], rel=0.01)
    assert payload["source_start_time"] == pytest.approx(candidate["start"], rel=0.01)
    assert payload["source_end_time"] == pytest.approx(candidate["end"], rel=0.01)
    assert payload["segments"]

    fetched = client.get(f"/api/projects/{project_id}/clips/{candidate_id}/captions")
    assert fetched.status_code == 200
    assert fetched.json()["clip_id"] == candidate_id


def test_candidate_caption_failure_is_retryable(sample_project, temp_backend_dirs, monkeypatch):
    from app.services.transcript_store import load_workflow_transcript
    from app.services.transcription import TranscriptionProcessError

    client = TestClient(app)
    project_id = sample_project["project_id"]
    _write_discovery_transcript(sample_project, temp_backend_dirs, _long_segments(20))
    assert client.post(f"/api/projects/{project_id}/analyze").status_code == 200
    assert client.post(f"/api/projects/{project_id}/select-clips", json={}).status_code == 200
    candidate_id = client.get(f"/api/projects/{project_id}/clip-candidates").json()["candidates"][0][
        "clip_id"
    ]

    attempts = {"count": 0}

    def _fail_once(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TranscriptionProcessError("Temporary retranscription failure.")
        return load_workflow_transcript(kwargs["project_id"])

    monkeypatch.setattr(
        "app.services.clip_captions.load_or_retranscribe_clip_quality_transcript",
        _fail_once,
    )

    first = client.post(f"/api/projects/{project_id}/clips/{candidate_id}/captions/generate")
    assert first.status_code == 422

    second = client.post(f"/api/projects/{project_id}/clips/{candidate_id}/captions/generate")
    assert second.status_code == 200
    assert second.json()["segments"]
