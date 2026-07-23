from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.project import ProcessingStatus
from app.services.project_store import create_project_metadata, load_project


@pytest.fixture(autouse=True)
def mock_clip_quality_transcript_loader(monkeypatch, request):
    if request.node.get_closest_marker("no_clip_quality_mock"):
        return

    from app.services.clip_captions import ClipCaptionsGenerationError
    from app.services.transcript_store import load_workflow_transcript
    from app.services.transcription import TranscriptNotFoundError

    def _loader(**kwargs):
        try:
            return load_workflow_transcript(kwargs["project_id"])
        except TranscriptNotFoundError as exc:
            raise ClipCaptionsGenerationError(
                "No transcript available. Transcribe the project before generating captions."
            ) from exc

    monkeypatch.setattr(
        "app.services.clip_captions.load_or_retranscribe_clip_quality_transcript",
        _loader,
    )


@pytest.fixture(autouse=True)
def isolate_analysis_settings(monkeypatch):
    """Keep tests offline and deterministic regardless of backend/.env."""
    monkeypatch.setattr(settings, "analysis_provider", "heuristic")
    monkeypatch.setattr(settings, "analysis_api_key", "")
    monkeypatch.setattr(settings, "analysis_external_provider", "openai")


@pytest.fixture()
def temp_backend_dirs(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    audio_dir = tmp_path / "audio"
    processed_dir = tmp_path / "processed"
    transcripts_dir = tmp_path / "transcripts"
    analysis_dir = tmp_path / "analysis"
    clip_candidates_dir = tmp_path / "clip_candidates"
    visual_analysis_dir = tmp_path / "visual_analysis"
    upload_dir.mkdir()
    audio_dir.mkdir()
    processed_dir.mkdir()
    transcripts_dir.mkdir()
    analysis_dir.mkdir()
    clip_candidates_dir.mkdir()
    visual_analysis_dir.mkdir()

    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "audio_dir", audio_dir)
    monkeypatch.setattr(settings, "processed_dir", processed_dir)
    monkeypatch.setattr(settings, "transcripts_dir", transcripts_dir)
    monkeypatch.setattr(settings, "analysis_dir", analysis_dir)
    monkeypatch.setattr(settings, "clip_candidates_dir", clip_candidates_dir)
    monkeypatch.setattr(settings, "visual_analysis_dir", visual_analysis_dir)
    return {
        "upload_dir": upload_dir,
        "audio_dir": audio_dir,
        "processed_dir": processed_dir,
        "transcripts_dir": transcripts_dir,
        "analysis_dir": analysis_dir,
        "clip_candidates_dir": clip_candidates_dir,
        "visual_analysis_dir": visual_analysis_dir,
    }


@pytest.fixture()
def sample_project(temp_backend_dirs):
    project_id = str(uuid.uuid4())
    project_dir = temp_backend_dirs["upload_dir"] / project_id
    project_dir.mkdir()
    video_path = project_dir / "sample.mp4"
    video_path.write_bytes(b"fake-video-content")

    create_project_metadata(
        project_id=project_id,
        original_filename="sample.mp4",
        stored_video_path=f"{project_id}/sample.mp4",
        size_bytes=video_path.stat().st_size,
    )
    return {
        "project_id": project_id,
        "video_path": video_path,
        "project": load_project(project_id),
    }


@pytest.fixture()
def ffprobe_video_payload():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30000/1001",
                "duration": "10.5",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
        "format": {
            "duration": "10.5",
            "size": "2048",
        },
    }


@pytest.fixture()
def ffprobe_no_audio_payload():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "24/1",
                "r_frame_rate": "24/1",
            }
        ],
        "format": {
            "duration": "5.0",
            "size": "1024",
        },
    }
