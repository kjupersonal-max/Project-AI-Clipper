from __future__ import annotations

import json
import uuid
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.project import ProcessingStatus, VideoMetadata
from app.services.clip_export import (
    ClipExportProcessError,
    ClipExportValidationError,
    export_project_clip,
    sanitize_clip_name,
)
from app.services.project_store import load_project, save_project
from app.services.video_processing import FFmpegNotAvailableError


def _completed_process(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def _set_video_metadata(sample_project, *, duration: float = 10.5):
    project = load_project(sample_project["project_id"])
    project.video_metadata = VideoMetadata(
        duration_seconds=duration,
        width=1920,
        height=1080,
        has_video=True,
        has_audio=True,
    )
    save_project(project)


def _fake_ffmpeg_run_factory(*, fail: bool = False, empty_output: bool = False):
    def fake_run(command, timeout_seconds):
        if command[-1] == "-version":
            return _completed_process(command, stdout=f"{Path(command[0]).stem} version 6.0")

        if Path(command[0]).stem == "ffmpeg" and command[1:3] == ["-hide_banner", "-loglevel"]:
            output_path = Path(command[-1])
            if fail:
                output_path.write_bytes(b"partial")
                return _completed_process(command, stderr="Error while encoding stream", code=1)
            if empty_output:
                output_path.write_bytes(b"")
                return _completed_process(command)
            output_path.write_bytes(b"\x00\x00\x00\x20ftypmp42")
            return _completed_process(command)

        raise AssertionError(f"Unexpected command: {command}")

    return fake_run


def test_successful_clip_export(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        response = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=5.0,
            clip_name="Best Moment",
        )

    assert response.clip_id
    assert response.project_id == sample_project["project_id"]
    assert response.filename == "Best_Moment.mp4"
    assert response.relative_path.endswith("/clips/Best_Moment.mp4")
    assert response.media_url == (
        f"/api/projects/{sample_project['project_id']}/media/clips/{response.clip_id}"
    )
    assert response.start_time == pytest.approx(1.0)
    assert response.end_time == pytest.approx(5.0)
    assert response.duration == pytest.approx(4.0)
    assert response.file_size_bytes > 0
    assert response.clip_name == "Best Moment"
    assert response.export_status == ProcessingStatus.COMPLETED
    assert response.created_at

    clip_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / response.filename
    )
    assert clip_path.exists()
    assert clip_path.stat().st_size > 0

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["exports"]) == 1
    assert manifest["exports"][0]["clip_id"] == response.clip_id


def test_export_endpoint_success(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    client = TestClient(app)

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/clips/export",
            json={"start_time": 0.5, "end_time": 3.5, "clip_name": "intro"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["export_status"] == "completed"
    assert body["filename"] == "intro.mp4"
    assert body["duration"] == pytest.approx(3.0)

    media_response = client.get(
        f"/api/projects/{sample_project['project_id']}/media/clips/{body['clip_id']}"
    )
    assert media_response.status_code == 200
    assert media_response.headers["content-type"].startswith("video/mp4")


def test_invalid_start_time_negative(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)

    with pytest.raises(ClipExportValidationError, match="start_time must be"):
        export_project_clip(
            sample_project["project_id"],
            start_time=-0.1,
            end_time=2.0,
        )


def test_invalid_end_before_start(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)

    with pytest.raises(ClipExportValidationError, match="end_time must be greater"):
        export_project_clip(
            sample_project["project_id"],
            start_time=5.0,
            end_time=5.0,
        )


def test_end_beyond_video_duration(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project, duration=10.0)

    with pytest.raises(ClipExportValidationError, match="exceeds source video duration"):
        export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=11.0,
        )


def test_clip_duration_exceeds_maximum(sample_project, temp_backend_dirs, monkeypatch):
    _set_video_metadata(sample_project, duration=300.0)
    monkeypatch.setattr(settings, "clip_export_max_duration_seconds", 60.0)

    with pytest.raises(ClipExportValidationError, match="exceeds the maximum allowed"):
        export_project_clip(
            sample_project["project_id"],
            start_time=0.0,
            end_time=90.0,
        )


def test_missing_project(temp_backend_dirs):
    client = TestClient(app)
    missing_id = "11111111-1111-4111-8111-111111111111"
    response = client.post(
        f"/api/projects/{missing_id}/clips/export",
        json={"start_time": 0.0, "end_time": 1.0},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


def test_missing_source_video(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    sample_project["video_path"].unlink()
    client = TestClient(app)

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/clips/export",
            json={"start_time": 0.0, "end_time": 1.0},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Uploaded video file not found."


def test_ffmpeg_failure_cleans_up_partial_output(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    clips_dir = temp_backend_dirs["processed_dir"] / sample_project["project_id"] / "clips"

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(fail=True),
    ):
        with pytest.raises(ClipExportProcessError):
            export_project_clip(
                sample_project["project_id"],
                start_time=0.0,
                end_time=2.0,
            )

    assert not list(clips_dir.glob("*.part.mp4")) if clips_dir.exists() else True
    assert not list(clips_dir.glob("*.mp4")) if clips_dir.exists() else True


def test_ffmpeg_missing_returns_503(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    client = TestClient(app)

    with patch(
        "app.services.clip_export.ensure_ffmpeg_tools",
        side_effect=FFmpegNotAvailableError("ffmpeg was not found in PATH."),
    ):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/clips/export",
            json={"start_time": 0.0, "end_time": 1.0},
        )

    assert response.status_code == 503
    assert "ffmpeg" in response.json()["detail"].lower()


def test_sanitize_clip_name():
    assert sanitize_clip_name("  My Clip!!!  ") == "My_Clip"
    assert sanitize_clip_name("../../../etc/passwd") == "etcpasswd"
    assert sanitize_clip_name("!!!") == "clip"


def test_filename_collision_handling(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    clips_dir = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
    )
    clips_dir.mkdir(parents=True, exist_ok=True)
    (clips_dir / "highlight.mp4").write_bytes(b"existing")

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        first = export_project_clip(
            sample_project["project_id"],
            start_time=0.0,
            end_time=1.0,
            clip_name="highlight",
        )
        second = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=2.0,
            clip_name="highlight",
        )

    assert first.filename == "highlight_2.mp4"
    assert second.filename == "highlight_3.mp4"


def test_invalid_candidate_id(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)

    with pytest.raises(ClipExportValidationError, match="Clip candidate"):
        export_project_clip(
            sample_project["project_id"],
            start_time=0.0,
            end_time=1.0,
            candidate_id="missing-candidate",
        )


def test_export_clip_not_found(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    client = TestClient(app)
    clip_id = str(uuid.uuid4())

    response = client.get(
        f"/api/projects/{sample_project['project_id']}/media/clips/{clip_id}"
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
