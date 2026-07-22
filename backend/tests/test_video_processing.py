from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.video_processing import (
    FFmpegProcessError,
    extract_project_audio,
    inspect_project_video,
)


def _completed_process(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def test_successful_metadata_inspection(sample_project, ffprobe_video_payload):
    stdout = json.dumps(ffprobe_video_payload)

    with patch(
        "app.services.video_processing._run_command",
        side_effect=[
            _completed_process(["ffprobe", "-version"], stdout="ffprobe version 6.0"),
            _completed_process(["ffmpeg", "-version"], stdout="ffmpeg version 6.0"),
            _completed_process(["ffprobe"], stdout=stdout),
        ],
    ):
        metadata = inspect_project_video(sample_project["project_id"])

    assert metadata.has_video is True
    assert metadata.has_audio is True
    assert metadata.width == 1920
    assert metadata.height == 1080
    assert metadata.video_codec == "h264"
    assert metadata.audio_codec == "aac"
    assert metadata.sample_rate == 48000
    assert metadata.audio_channels == 2
    assert metadata.duration_seconds == pytest.approx(10.5)
    assert metadata.frame_rate == pytest.approx(30000 / 1001)
    assert metadata.aspect_ratio == "16:9"


def test_video_with_no_audio(sample_project, ffprobe_no_audio_payload):
    stdout = json.dumps(ffprobe_no_audio_payload)

    with patch(
        "app.services.video_processing._run_command",
        side_effect=[
            _completed_process(["ffprobe", "-version"], stdout="ffprobe version 6.0"),
            _completed_process(["ffmpeg", "-version"], stdout="ffmpeg version 6.0"),
            _completed_process(["ffprobe"], stdout=stdout),
            _completed_process(["ffprobe", "-version"], stdout="ffprobe version 6.0"),
            _completed_process(["ffmpeg", "-version"], stdout="ffmpeg version 6.0"),
            _completed_process(["ffprobe"], stdout=stdout),
        ],
    ):
        metadata = inspect_project_video(sample_project["project_id"])
        assert metadata.has_video is True
        assert metadata.has_audio is False

        with pytest.raises(FFmpegProcessError, match="does not contain an audio track"):
            extract_project_audio(sample_project["project_id"])


def test_invalid_project_id():
    client = TestClient(app)
    response = client.get("/api/projects/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid project ID format."


def test_missing_project():
    client = TestClient(app)
    response = client.get("/api/projects/11111111-1111-4111-8111-111111111111")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


def test_missing_video_file(temp_backend_dirs, sample_project):
    sample_project["video_path"].unlink()

    with patch(
        "app.services.video_processing._run_command",
        side_effect=[
            _completed_process(["ffprobe", "-version"], stdout="ffprobe version 6.0"),
            _completed_process(["ffmpeg", "-version"], stdout="ffmpeg version 6.0"),
        ],
    ):
        client = TestClient(app)
        response = client.post(f"/api/projects/{sample_project['project_id']}/inspect")

    assert response.status_code == 404
    assert response.json()["detail"] == "Uploaded video file not found."


def test_audio_extraction_success(sample_project, ffprobe_video_payload, temp_backend_dirs):
    probe_stdout = json.dumps(ffprobe_video_payload)
    audio_probe_stdout = json.dumps(
        {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "pcm_s16le",
                    "sample_rate": "16000",
                    "channels": 1,
                }
            ],
            "format": {"duration": "10.5", "size": "320044"},
        }
    )

    def fake_run(command, timeout_seconds):
        if Path(command[0]).stem == "ffmpeg" and command[1:3] == ["-hide_banner", "-loglevel"]:
            output_path = command[-1]
            Path(output_path).write_bytes(b"RIFF....WAVEfmt ")
            return _completed_process(command)
        if Path(command[0]).stem == "ffprobe" and "-show_streams" in command:
            if str(command[-1]).endswith(".wav"):
                return _completed_process(command, stdout=audio_probe_stdout)
            return _completed_process(command, stdout=probe_stdout)
        if command[-1] == "-version":
            return _completed_process(command, stdout=f"{Path(command[0]).stem} version 6.0")
        raise AssertionError(f"Unexpected command: {command}")

    with patch("app.services.video_processing._run_command", side_effect=fake_run):
        relative_path, duration = extract_project_audio(sample_project["project_id"])

    assert relative_path == f"{sample_project['project_id']}/audio.wav"
    assert duration == pytest.approx(10.5)
    output_file = temp_backend_dirs["audio_dir"] / sample_project["project_id"] / "audio.wav"
    assert output_file.exists()
    assert output_file.stat().st_size > 0


def test_cleanup_after_extraction_failure(sample_project, ffprobe_video_payload, temp_backend_dirs):
    probe_stdout = json.dumps(ffprobe_video_payload)

    def failing_run(command, timeout_seconds):
        if Path(command[0]).stem == "ffmpeg" and command[1:3] == ["-hide_banner", "-loglevel"]:
            output_path = command[-1]
            Path(output_path).write_bytes(b"partial")
            return _completed_process(command, stderr="Error while decoding stream", code=1)
        if Path(command[0]).stem == "ffprobe" and "-show_streams" in command:
            return _completed_process(command, stdout=probe_stdout)
        if command[-1] == "-version":
            return _completed_process(command, stdout=f"{Path(command[0]).stem} version 6.0")
        raise AssertionError(f"Unexpected command: {command}")

    with patch("app.services.video_processing._run_command", side_effect=failing_run):
        with pytest.raises(FFmpegProcessError):
            extract_project_audio(sample_project["project_id"])

    audio_dir = temp_backend_dirs["audio_dir"] / sample_project["project_id"]
    assert not audio_dir.exists() or not any(audio_dir.glob("*.part.wav"))


def test_inspect_endpoint_updates_project(sample_project, ffprobe_video_payload):
    stdout = json.dumps(ffprobe_video_payload)
    client = TestClient(app)

    with patch(
        "app.services.video_processing._run_command",
        side_effect=[
            _completed_process(["ffprobe", "-version"], stdout="ffprobe version 6.0"),
            _completed_process(["ffmpeg", "-version"], stdout="ffmpeg version 6.0"),
            _completed_process(["ffprobe"], stdout=stdout),
        ],
    ):
        response = client.post(f"/api/projects/{sample_project['project_id']}/inspect")

    assert response.status_code == 200
    body = response.json()
    assert body["inspection_status"] == "completed"
    assert body["video_metadata"]["width"] == 1920

    project_response = client.get(f"/api/projects/{sample_project['project_id']}")
    assert project_response.status_code == 200
    assert project_response.json()["inspection_status"] == "completed"
