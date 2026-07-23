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
    ClipExportNotFoundError,
    ClipExportProcessError,
    ClipExportValidationError,
    delete_project_clip,
    export_project_clip,
    favorite_project_clip,
    list_project_clip_exports,
    rename_project_clip,
    sanitize_clip_name,
    trim_project_clip,
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


def _export_clip(
    sample_project,
    *,
    start_time: float,
    end_time: float,
    clip_name: str,
):
    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        return export_project_clip(
            sample_project["project_id"],
            start_time=start_time,
            end_time=end_time,
            clip_name=clip_name,
        )


def _trim_clip(
    sample_project,
    source_clip_id: str,
    *,
    start_time: float,
    end_time: float,
    clip_name: str | None = None,
):
    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        return trim_project_clip(
            sample_project["project_id"],
            source_clip_id,
            start_time=start_time,
            end_time=end_time,
            clip_name=clip_name,
        )


def test_list_clip_exports_empty(sample_project, temp_backend_dirs):
    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/clips/exports")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == sample_project["project_id"]
    assert body["exports"] == []


def test_list_clip_exports_multiple_newest_first(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)

    first = _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="first")
    second = _export_clip(sample_project, start_time=1.0, end_time=2.0, clip_name="second")

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for export, created_at in zip(manifest["exports"], ["2026-07-22T10:00:00Z", "2026-07-22T11:00:00Z"], strict=True):
        export["created_at"] = created_at
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/clips/exports")

    assert response.status_code == 200
    exports = response.json()["exports"]
    assert len(exports) == 2
    assert exports[0]["clip_id"] == second.clip_id
    assert exports[1]["clip_id"] == first.clip_id
    assert exports[0]["media_url"].endswith(second.clip_id)
    assert exports[0]["export_status"] == "completed"


def test_list_clip_exports_missing_project(temp_backend_dirs):
    client = TestClient(app)
    missing_id = "11111111-1111-4111-8111-111111111111"
    response = client.get(f"/api/projects/{missing_id}/clips/exports")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found."


def test_list_clip_exports_excludes_missing_file(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="missing-file")

    clip_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / exported.filename
    )
    clip_path.unlink()

    exports = list_project_clip_exports(sample_project["project_id"])
    assert exports == []


def test_list_clip_exports_skips_malformed_record(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="valid")

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["exports"].append({"clip_id": "bad-record", "filename": 123})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    exports = list_project_clip_exports(sample_project["project_id"])
    assert len(exports) == 1
    assert exports[0].clip_id == exported.clip_id


def test_list_clip_exports_handles_malformed_manifest(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    clips_dir = temp_backend_dirs["processed_dir"] / sample_project["project_id"] / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = clips_dir / "exports.json"
    manifest_path.write_text("{not-json", encoding="utf-8")

    exports = list_project_clip_exports(sample_project["project_id"])
    assert exports == []


def test_list_clip_exports_endpoint(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="saved")

    client = TestClient(app)
    response = client.get(f"/api/projects/{sample_project['project_id']}/clips/exports")

    assert response.status_code == 200
    body = response.json()
    assert len(body["exports"]) == 1
    assert body["exports"][0]["clip_id"] == exported.clip_id
    assert body["exports"][0]["filename"] == exported.filename


def test_list_clip_exports_route_is_registered():
    client = TestClient(app)
    openapi_paths = client.get("/openapi.json").json()["paths"]

    assert "/api/projects/{project_id}/clips/exports" in openapi_paths
    assert "get" in openapi_paths["/api/projects/{project_id}/clips/exports"]


def test_rename_clip_success(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Original Name",
    )

    updated = rename_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        clip_name="Renamed Clip",
    )

    assert updated.clip_id == exported.clip_id
    assert updated.clip_name == "Renamed Clip"
    assert updated.filename == exported.filename

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["exports"][0]["clip_name"] == "Renamed Clip"


def test_rename_clip_trims_whitespace(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Original",
    )

    updated = rename_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        clip_name="  Trimmed Name  ",
    )

    assert updated.clip_name == "Trimmed Name"


def test_rename_clip_empty_name_rejected(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Original",
    )

    with pytest.raises(ClipExportValidationError, match="must not be empty"):
        rename_project_clip(
            sample_project["project_id"],
            exported.clip_id,
            clip_name="   ",
        )


def test_rename_clip_missing_project(temp_backend_dirs):
    missing_id = "11111111-1111-4111-8111-111111111111"

    with pytest.raises(Exception) as exc_info:
        rename_project_clip(missing_id, "clip-id", clip_name="New Name")

    assert exc_info.value.status_code == 404


def test_rename_clip_missing_clip(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="Original")
    missing_clip_id = str(uuid.uuid4())

    with pytest.raises(ClipExportNotFoundError, match="was not found"):
        rename_project_clip(
            sample_project["project_id"],
            missing_clip_id,
            clip_name="New Name",
        )


def test_rename_clip_endpoint(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Original",
    )
    client = TestClient(app)

    response = client.patch(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}",
        json={"clip_name": "Endpoint Rename"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["clip_name"] == "Endpoint Rename"
    assert body["clip_id"] == exported.clip_id
    assert body["filename"] == exported.filename


def test_delete_clip_success(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="To Delete",
    )

    clip_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / exported.filename
    )
    assert clip_path.exists()

    deleted = delete_project_clip(sample_project["project_id"], exported.clip_id)

    assert deleted.clip_id == exported.clip_id
    assert not clip_path.exists()

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["exports"] == []

    exports = list_project_clip_exports(sample_project["project_id"])
    assert exports == []


def test_delete_clip_when_file_already_missing(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Missing File",
    )

    clip_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / exported.filename
    )
    clip_path.unlink()

    delete_project_clip(sample_project["project_id"], exported.clip_id)

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["exports"] == []


def test_delete_clip_manifest_updated_correctly(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    first = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Keep Me",
    )
    second = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=2.0,
        clip_name="Delete Me",
    )

    delete_project_clip(sample_project["project_id"], second.clip_id)

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["exports"]) == 1
    assert manifest["exports"][0]["clip_id"] == first.clip_id
    assert manifest["exports"][0]["clip_name"] == "Keep Me"

    first_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / first.filename
    )
    second_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / second.filename
    )
    assert first_path.exists()
    assert not second_path.exists()


def test_delete_clip_unrelated_clips_remain_untouched(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    first = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="First",
    )
    second = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=2.0,
        clip_name="Second",
    )
    third = _export_clip(
        sample_project,
        start_time=2.0,
        end_time=3.0,
        clip_name="Third",
    )

    delete_project_clip(sample_project["project_id"], second.clip_id)

    exports = list_project_clip_exports(sample_project["project_id"])
    remaining_ids = {export.clip_id for export in exports}
    assert remaining_ids == {first.clip_id, third.clip_id}


def test_delete_clip_missing_project(temp_backend_dirs):
    missing_id = "11111111-1111-4111-8111-111111111111"

    with pytest.raises(Exception) as exc_info:
        delete_project_clip(missing_id, "clip-id")

    assert exc_info.value.status_code == 404


def test_delete_clip_missing_clip(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="Original")
    missing_clip_id = str(uuid.uuid4())

    with pytest.raises(ClipExportNotFoundError, match="was not found"):
        delete_project_clip(sample_project["project_id"], missing_clip_id)


def test_delete_clip_endpoint(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Endpoint Delete",
    )
    client = TestClient(app)

    response = client.delete(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["clip_id"] == exported.clip_id
    assert body["project_id"] == sample_project["project_id"]
    assert body["message"] == "Exported clip deleted successfully."


def test_favorite_clip_true(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Favorite Me",
    )

    updated = favorite_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        is_favorite=True,
    )

    assert updated.clip_id == exported.clip_id
    assert updated.is_favorite is True

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["exports"][0]["is_favorite"] is True


def test_favorite_clip_false(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Unfavorite Me",
    )

    favorite_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        is_favorite=True,
    )
    updated = favorite_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        is_favorite=False,
    )

    assert updated.is_favorite is False

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["exports"][0]["is_favorite"] is False


def test_favorite_clip_missing_project(temp_backend_dirs):
    missing_id = "11111111-1111-4111-8111-111111111111"

    with pytest.raises(Exception) as exc_info:
        favorite_project_clip(missing_id, "clip-id", is_favorite=True)

    assert exc_info.value.status_code == 404


def test_favorite_clip_missing_clip(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    _export_clip(sample_project, start_time=0.0, end_time=1.0, clip_name="Original")
    missing_clip_id = str(uuid.uuid4())

    with pytest.raises(ClipExportNotFoundError, match="was not found"):
        favorite_project_clip(
            sample_project["project_id"],
            missing_clip_id,
            is_favorite=True,
        )


def test_favorite_clip_older_manifest_without_is_favorite(
    sample_project,
    temp_backend_dirs,
):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Legacy Clip",
    )

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["exports"][0]["is_favorite"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    exports = list_project_clip_exports(sample_project["project_id"])
    assert len(exports) == 1
    assert exports[0].clip_id == exported.clip_id
    assert exports[0].is_favorite is False

    updated = favorite_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        is_favorite=True,
    )
    assert updated.is_favorite is True


def test_favorite_clip_persistence_after_reload(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Persist Favorite",
    )

    favorite_project_clip(
        sample_project["project_id"],
        exported.clip_id,
        is_favorite=True,
    )

    exports = list_project_clip_exports(sample_project["project_id"])
    assert len(exports) == 1
    assert exports[0].is_favorite is True


def test_favorite_clip_unrelated_clips_unchanged(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    first = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="First",
    )
    second = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=2.0,
        clip_name="Second",
    )

    favorite_project_clip(
        sample_project["project_id"],
        first.clip_id,
        is_favorite=True,
    )

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records_by_id = {record["clip_id"]: record for record in manifest["exports"]}

    assert records_by_id[first.clip_id]["is_favorite"] is True
    assert records_by_id[second.clip_id]["is_favorite"] is False


def test_favorite_clip_endpoint(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    exported = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=1.0,
        clip_name="Endpoint Favorite",
    )
    client = TestClient(app)

    response = client.patch(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/favorite",
        json={"is_favorite": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["clip_id"] == exported.clip_id
    assert body["is_favorite"] is True


def test_trim_clip_success(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=5.0,
        clip_name="Parent Clip",
    )

    trimmed = _trim_clip(
        sample_project,
        parent.clip_id,
        start_time=2.0,
        end_time=4.0,
        clip_name="Trimmed Clip",
    )

    assert trimmed.clip_id != parent.clip_id
    assert trimmed.start_time == pytest.approx(2.0)
    assert trimmed.end_time == pytest.approx(4.0)
    assert trimmed.duration == pytest.approx(2.0)
    assert trimmed.clip_name == "Trimmed Clip"
    assert trimmed.candidate_id == parent.candidate_id
    assert trimmed.is_favorite is False

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["exports"]) == 2

    parent_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / parent.filename
    )
    trimmed_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / trimmed.filename
    )
    assert parent_path.exists()
    assert trimmed_path.exists()
    assert parent_path.read_bytes() != trimmed_path.read_bytes() or parent.filename != trimmed.filename


def test_trim_clip_invalid_timestamps_before_parent_start(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=2.0,
        end_time=5.0,
        clip_name="Parent Clip",
    )

    with pytest.raises(ClipExportValidationError, match="cannot be earlier"):
        trim_project_clip(
            sample_project["project_id"],
            parent.clip_id,
            start_time=1.0,
            end_time=4.0,
        )


def test_trim_clip_end_before_start(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=5.0,
        clip_name="Parent Clip",
    )

    with pytest.raises(ClipExportValidationError, match="greater than start_time"):
        trim_project_clip(
            sample_project["project_id"],
            parent.clip_id,
            start_time=4.0,
            end_time=3.0,
        )


def test_trim_clip_zero_length(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=5.0,
        clip_name="Parent Clip",
    )

    with pytest.raises(ClipExportValidationError, match="greater than start_time"):
        trim_project_clip(
            sample_project["project_id"],
            parent.clip_id,
            start_time=3.0,
            end_time=3.0,
        )


def test_trim_clip_missing_clip(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    _export_clip(
        sample_project,
        start_time=1.0,
        end_time=5.0,
        clip_name="Parent Clip",
    )
    missing_clip_id = str(uuid.uuid4())

    with pytest.raises(ClipExportNotFoundError, match="was not found"):
        trim_project_clip(
            sample_project["project_id"],
            missing_clip_id,
            start_time=2.0,
            end_time=4.0,
        )


def test_trim_clip_manifest_creation(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=0.0,
        end_time=3.0,
        clip_name="Manifest Parent",
    )

    trimmed = _trim_clip(
        sample_project,
        parent.clip_id,
        start_time=0.5,
        end_time=2.5,
    )

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    clip_ids = {record["clip_id"] for record in manifest["exports"]}
    assert clip_ids == {parent.clip_id, trimmed.clip_id}


def test_trim_clip_original_preserved(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=6.0,
        clip_name="Original Clip",
    )

    parent_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / parent.filename
    )
    original_bytes = parent_path.read_bytes()
    original_manifest_entry = {
        "clip_id": parent.clip_id,
        "clip_name": parent.clip_name,
        "filename": parent.filename,
        "start_time": parent.start_time,
        "end_time": parent.end_time,
    }

    _trim_clip(
        sample_project,
        parent.clip_id,
        start_time=2.0,
        end_time=4.0,
    )

    assert parent_path.read_bytes() == original_bytes

    manifest_path = (
        temp_backend_dirs["processed_dir"]
        / sample_project["project_id"]
        / "clips"
        / "exports.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    preserved = next(record for record in manifest["exports"] if record["clip_id"] == parent.clip_id)
    assert preserved["clip_name"] == original_manifest_entry["clip_name"]
    assert preserved["filename"] == original_manifest_entry["filename"]
    assert preserved["start_time"] == original_manifest_entry["start_time"]
    assert preserved["end_time"] == original_manifest_entry["end_time"]


def test_trim_clip_endpoint(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    parent = _export_clip(
        sample_project,
        start_time=1.0,
        end_time=5.0,
        clip_name="Endpoint Parent",
    )
    client = TestClient(app)

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/clips/{parent.clip_id}/trim",
            json={"start_time": 2.0, "end_time": 4.0, "clip_name": "Endpoint Trimmed"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["clip_id"] != parent.clip_id
    assert body["clip_name"] == "Endpoint Trimmed"
    assert body["start_time"] == pytest.approx(2.0)
    assert body["end_time"] == pytest.approx(4.0)
