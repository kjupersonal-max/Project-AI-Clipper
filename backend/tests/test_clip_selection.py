from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.project import (
    ProcessingStatus,
    TranscriptDocument,
    TranscriptSegment,
)
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import analyze_project_timeline
from app.services.clip_selection import (
    ClipCandidatesNotFoundError,
    ClipSelectionAnalysisRequiredError,
    ClipSelectionProcessError,
    ClipSelectionTranscriptRequiredError,
    load_project_clip_candidates,
    select_project_clips,
)


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


def _write_completed_analysis(sample_project, temp_backend_dirs, segments: list[TranscriptSegment]):
    _write_completed_transcript(sample_project, temp_backend_dirs, segments)
    document = analyze_project_timeline(sample_project["project_id"])

    project = load_project(sample_project["project_id"])
    project.analysis_status = ProcessingStatus.COMPLETED
    project.analysis_path = f"{sample_project['project_id']}/analysis.json"
    project.analysis_provider = document.provider
    save_project(project)
    return document


@pytest.fixture()
def clip_selection_segments():
    return [
        TranscriptSegment(
            id=0,
            start=0.0,
            end=4.0,
            text="Wait, that was insane!",
            words=[],
        ),
        TranscriptSegment(
            id=1,
            start=4.0,
            end=8.0,
            text="lol that was actually funny",
            words=[],
        ),
        TranscriptSegment(
            id=2,
            start=8.0,
            end=12.0,
            text="Because this tip helps you learn the mechanic",
            words=[],
        ),
        TranscriptSegment(
            id=3,
            start=12.0,
            end=18.0,
            text="No way, that clutch was crazy!",
            words=[],
        ),
    ]


def test_select_clips_success(sample_project, temp_backend_dirs, clip_selection_segments):
    _write_completed_analysis(sample_project, temp_backend_dirs, clip_selection_segments)

    document = select_project_clips(
        sample_project["project_id"],
        min_duration_seconds=12.0,
        min_score=0.0,
    )

    assert document.candidate_count >= 1
    assert len(document.candidates) == document.candidate_count
    candidate = document.candidates[0]
    assert candidate.clip_id
    assert candidate.start >= 0.0
    assert candidate.end > candidate.start
    assert candidate.duration == pytest.approx(candidate.end - candidate.start, abs=0.01)
    assert candidate.segment_ids
    assert candidate.transcript_text
    assert 0.0 <= candidate.score <= 100.0
    assert 0.0 <= candidate.confidence <= 1.0
    assert candidate.primary_emotion
    assert 0.0 <= candidate.hook_score <= 10.0
    assert 0.0 <= candidate.payoff_score <= 10.0
    assert 0.0 <= candidate.standalone_score <= 10.0
    assert 0.0 <= candidate.context_dependency_score <= 10.0
    assert candidate.title_suggestion
    assert candidate.reason
    assert candidate.status == "proposed"

    output_path = (
        temp_backend_dirs["clip_candidates_dir"]
        / sample_project["project_id"]
        / "clip_candidates.json"
    )
    assert output_path.exists()


def test_select_clips_empty_when_no_strong_segments(sample_project, temp_backend_dirs):
    segments = [
        TranscriptSegment(
            id=0,
            start=0.0,
            end=20.0,
            text="okay",
            words=[],
        )
    ]
    _write_completed_analysis(sample_project, temp_backend_dirs, segments)

    document = select_project_clips(
        sample_project["project_id"],
        min_duration_seconds=5.0,
        min_score=0.0,
    )
    assert document.candidate_count == 0
    assert document.candidates == []


def test_select_clips_missing_transcript(sample_project):
    with pytest.raises(ClipSelectionTranscriptRequiredError):
        select_project_clips(sample_project["project_id"])


def test_select_clips_missing_analysis(sample_project, temp_backend_dirs, clip_selection_segments):
    _write_completed_transcript(sample_project, temp_backend_dirs, clip_selection_segments)

    with pytest.raises(ClipSelectionAnalysisRequiredError):
        select_project_clips(sample_project["project_id"])


def test_get_clip_candidates_success(sample_project, temp_backend_dirs, clip_selection_segments):
    _write_completed_analysis(sample_project, temp_backend_dirs, clip_selection_segments)
    select_project_clips(
        sample_project["project_id"],
        min_duration_seconds=12.0,
        min_score=0.0,
    )

    document = load_project_clip_candidates(sample_project["project_id"])
    assert document.candidate_count >= 0

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/clip-candidates")
    assert response.status_code == 200
    assert "candidates" in response.json()


def test_get_clip_candidates_missing(sample_project):
    with pytest.raises(ClipCandidatesNotFoundError):
        load_project_clip_candidates(sample_project["project_id"])

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/clip-candidates")
    assert response.status_code == 404
    assert "Clip candidates not found" in response.json()["detail"]


def test_select_clips_endpoint_updates_project(
    sample_project,
    temp_backend_dirs,
    clip_selection_segments,
):
    _write_completed_analysis(sample_project, temp_backend_dirs, clip_selection_segments)
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{sample_project['project_id']}/select-clips",
        json={"min_duration_seconds": 12.0, "min_score": 0.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["candidate_count"] >= 0

    project = load_project(sample_project["project_id"])
    assert project.clip_selection_status == ProcessingStatus.COMPLETED
    assert project.clip_candidates_path == f"{sample_project['project_id']}/clip_candidates.json"
    assert project.clip_candidate_count == body["candidate_count"]


def test_select_clips_missing_project():
    client = TestClient(app)
    response = client.post("/api/projects/11111111-1111-4111-8111-111111111111/select-clips")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


def test_get_clip_candidates_corrupted_file(
    sample_project,
    temp_backend_dirs,
    clip_selection_segments,
):
    _write_completed_analysis(sample_project, temp_backend_dirs, clip_selection_segments)
    select_project_clips(
        sample_project["project_id"],
        min_duration_seconds=12.0,
        min_score=0.0,
    )

    output_path = (
        temp_backend_dirs["clip_candidates_dir"]
        / sample_project["project_id"]
        / "clip_candidates.json"
    )
    output_path.write_text("{not valid json", encoding="utf-8")

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/clip-candidates")
    assert response.status_code == 500
    assert "corrupted" in response.json()["detail"].lower()


def test_select_clips_deduplicates_overlapping_candidates(
    sample_project,
    temp_backend_dirs,
    monkeypatch,
):
    segments = [
        TranscriptSegment(
            id=index,
            start=float(index * 5),
            end=float(index * 5 + 4),
            text=f"Wait insane clutch moment {index}!",
            words=[],
        )
        for index in range(6)
    ]
    _write_completed_analysis(sample_project, temp_backend_dirs, segments)

    document = select_project_clips(
        sample_project["project_id"],
        min_duration_seconds=8.0,
        max_duration_seconds=30.0,
        max_gap_seconds=3.0,
        max_candidates=3,
        min_score=0.0,
    )

    for left, right in zip(document.candidates, document.candidates[1:], strict=False):
        assert left.end <= right.start or right.end <= left.start or left.clip_id != right.clip_id


def test_select_clips_invalid_options(sample_project, temp_backend_dirs, clip_selection_segments):
    _write_completed_analysis(sample_project, temp_backend_dirs, clip_selection_segments)

    with pytest.raises(ClipSelectionProcessError):
        select_project_clips(
            sample_project["project_id"],
            min_duration_seconds=60.0,
            max_duration_seconds=15.0,
        )


def test_select_clips_endpoint_requires_analysis(
    sample_project,
    temp_backend_dirs,
    clip_selection_segments,
):
    _write_completed_transcript(sample_project, temp_backend_dirs, clip_selection_segments)
    client = TestClient(app)

    response = client.post(f"/api/projects/{sample_project['project_id']}/select-clips")
    assert response.status_code == 404
    assert "analysis" in response.json()["detail"].lower()

    project = load_project(sample_project["project_id"])
    assert project.clip_selection_status == ProcessingStatus.FAILED
