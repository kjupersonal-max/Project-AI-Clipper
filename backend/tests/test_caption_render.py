from __future__ import annotations

import json
import uuid
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ExportClipKind,
    ProcessingStatus,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
    VideoMetadata,
)
from app.services.caption_render import (
    CaptionRenderInProgressError,
    CaptionRenderProcessError,
    CaptionRenderValidationError,
    _build_ass_filter_value,
    _path_arg_for_ffmpeg,
    format_caption_render_error_detail,
    render_project_clip_captions,
)
from app.services.clip_captions import generate_clip_captions
from app.services.clip_export import (
    ClipExportNotFoundError,
    export_project_clip,
    list_project_clip_exports,
    locate_exported_clip,
)
from app.services.project_store import (
    get_clip_captions_path,
    get_clip_exports_manifest_path,
    get_transcript_output_path,
    load_project,
    save_project,
)


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


def _write_transcript(project_id: str, document: TranscriptDocument) -> None:
    transcript_path = get_transcript_output_path(project_id)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    project = load_project(project_id)
    project.transcript_path = f"{project_id}/transcript.json"
    project.transcription_status = ProcessingStatus.COMPLETED
    save_project(project)


def _sample_transcript(project_id: str) -> TranscriptDocument:
    return TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=10.5,
        segment_count=1,
        word_count=2,
        segments=[
            TranscriptSegment(
                id=0,
                start=0.0,
                end=2.5,
                text="Hello world",
                words=[
                    TranscriptWord(word="Hello", start=0.0, end=0.8, probability=0.99),
                    TranscriptWord(word="world", start=0.8, end=2.5, probability=0.98),
                ],
            )
        ],
    )


def _fake_ffmpeg_run_factory(*, fail: bool = False, empty_output: bool = False):
    def fake_run(command, timeout_seconds, cwd=None):
        if command[-1] == "-version":
            return _completed_process(command, stdout=f"{Path(command[0]).stem} version 6.0")

        if Path(command[0]).stem == "ffprobe":
            payload = {
                "format": {"duration": "4.0", "size": "32"},
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "codec_name": "h264",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "44100",
                        "channels": 2,
                    },
                ],
            }
            return _completed_process(command, stdout=json.dumps(payload))

        if Path(command[0]).stem == "ffmpeg" and command[1:3] == ["-hide_banner", "-loglevel"]:
            output_path = Path(command[-1])
            if cwd is not None:
                output_path = Path(cwd) / output_path
            if fail:
                output_path.write_bytes(b"partial")
                return _completed_process(command, stderr="Error reinitializing filters", code=1)
            if empty_output:
                output_path.write_bytes(b"")
                return _completed_process(command)
            output_path.write_bytes(b"\x00\x00\x00\x20ftypmp42")
            return _completed_process(command)

        raise AssertionError(f"Unexpected command: {command}")

    return fake_run


def _export_and_caption(sample_project):
    _set_video_metadata(sample_project)
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))

    with (
        patch(
            "app.services.clip_export._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        exported = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=5.0,
            clip_name="Render Source",
        )

    generate_clip_captions(sample_project["project_id"], exported.clip_id)
    return exported


def test_successful_captioned_render(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)
    _, source_path = locate_exported_clip(sample_project["project_id"], exported.clip_id)
    original_size = source_path.stat().st_size

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        rendered = render_project_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
        )

    assert rendered.export_kind == ExportClipKind.CAPTIONED
    assert rendered.source_clip_id == exported.clip_id
    assert rendered.clip_id != exported.clip_id
    assert "(captioned)" in (rendered.clip_name or "")
    assert rendered.caption_style_preset == "custom"

    _, reloaded_source = locate_exported_clip(sample_project["project_id"], exported.clip_id)
    assert reloaded_source.stat().st_size == original_size


def test_render_appends_manifest_entry(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        rendered = render_project_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
        )

    exports = list_project_clip_exports(sample_project["project_id"])
    clip_ids = {item.clip_id for item in exports}
    assert exported.clip_id in clip_ids
    assert rendered.clip_id in clip_ids


def test_render_requires_captions(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    with (
        patch(
            "app.services.clip_export._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        exported = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=5.0,
        )

    with pytest.raises(CaptionRenderValidationError, match="Captions are required"):
        render_project_clip_captions(sample_project["project_id"], exported.clip_id)


def test_render_rejects_captioned_source(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        rendered = render_project_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
        )

    with pytest.raises(CaptionRenderValidationError, match="cannot be re-rendered"):
        render_project_clip_captions(sample_project["project_id"], rendered.clip_id)


def test_render_uses_saved_style(sample_project, temp_backend_dirs):
    from app.models.project import CaptionStyle, CaptionStylePresetId
    from app.services.clip_captions import update_clip_caption_style

    exported = _export_and_caption(sample_project)
    update_clip_caption_style(
        sample_project["project_id"],
        exported.clip_id,
        CaptionStyle(preset_id=CaptionStylePresetId.BOLD_POP),
    )

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        rendered = render_project_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
        )

    assert rendered.caption_style_preset == "bold-pop"


def test_build_ass_filter_uses_relative_filename_in_work_dir(tmp_path):
    work_dir = tmp_path / "Project AI clipper" / "clips"
    work_dir.mkdir(parents=True)
    ass_path = work_dir / "clip.part.ass"
    ass_path.write_text("[Script Info]", encoding="utf-8")

    assert _build_ass_filter_value(ass_path, work_dir) == "ass=clip.part.ass"


def test_path_arg_for_ffmpeg_uses_relative_name_in_work_dir(tmp_path):
    work_dir = tmp_path / "Project AI clipper" / "clips"
    work_dir.mkdir(parents=True)
    clip_path = work_dir / "Render Source.mp4"
    clip_path.write_bytes(b"data")

    assert _path_arg_for_ffmpeg(clip_path, work_dir) == "Render Source.mp4"


def test_format_caption_render_error_detail_includes_stderr():
    exc = CaptionRenderProcessError(
        "Caption render FFmpeg failed with exit code 1.",
        command=["ffmpeg", "-vf", "ass=clip.part.ass"],
        stderr="Error opening output file: full diagnostic text",
    )
    detail = format_caption_render_error_detail(exc)
    assert "full diagnostic text" in detail
    assert "FFmpeg command:" in detail
    assert "FFmpeg stderr:" in detail


def test_render_word_level_input(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ) as run_mock,
    ):
        render_project_clip_captions(sample_project["project_id"], exported.clip_id)

    ffmpeg_commands = [
        call.args[0]
        for call in run_mock.call_args_list
        if Path(call.args[0][0]).stem == "ffmpeg"
    ]
    assert ffmpeg_commands
    command = ffmpeg_commands[-1]
    vf_index = command.index("-vf")
    ass_filter = command[vf_index + 1]
    expected_ass = command[-1].replace(".part.mp4", ".part.ass")
    assert ass_filter == f"ass={expected_ass}"
    assert "C:" not in ass_filter
    assert run_mock.call_args.kwargs.get("cwd")
    assert "-c:a" in command
    assert "copy" in command
    assert "-an" not in command


def test_render_segment_fallback(sample_project, temp_backend_dirs):
    _set_video_metadata(sample_project)
    transcript = TranscriptDocument(
        project_id=sample_project["project_id"],
        language="en",
        duration=10.5,
        segment_count=1,
        word_count=0,
        segments=[
            TranscriptSegment(
                id=0,
                start=1.0,
                end=4.0,
                text="Segment only text",
                words=[],
            )
        ],
    )
    _write_transcript(sample_project["project_id"], transcript)

    with (
        patch(
            "app.services.clip_export._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        exported = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=5.0,
        )

    generate_clip_captions(sample_project["project_id"], exported.clip_id)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        rendered = render_project_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
        )

    assert rendered.export_kind == ExportClipKind.CAPTIONED


def test_render_missing_source_file(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)
    _, source_path = locate_exported_clip(sample_project["project_id"], exported.clip_id)
    source_path.unlink()

    with pytest.raises(ClipExportNotFoundError):
        render_project_clip_captions(sample_project["project_id"], exported.clip_id)


def test_render_ffmpeg_failure_cleanup(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)
    _, source_path = locate_exported_clip(sample_project["project_id"], exported.clip_id)
    clips_dir = source_path.parent

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(fail=True),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(fail=True),
        ),
    ):
        with pytest.raises(CaptionRenderProcessError):
            render_project_clip_captions(sample_project["project_id"], exported.clip_id)

    leftover = list(clips_dir.glob("*captioned*.part.mp4"))
    assert leftover == []


def test_render_empty_output_rejected(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(empty_output=True),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(empty_output=True),
        ),
    ):
        with pytest.raises(CaptionRenderProcessError):
            render_project_clip_captions(sample_project["project_id"], exported.clip_id)


def test_render_endpoint(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)
    client = TestClient(app)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        response = client.post(
            f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions/render"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["export_kind"] == "captioned"
    assert body["source_clip_id"] == exported.clip_id


def test_backwards_compatible_manifest_entries(sample_project, temp_backend_dirs):
    exported = _export_and_caption(sample_project)
    manifest_path = get_clip_exports_manifest_path(sample_project["project_id"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["exports"][0].pop("export_kind", None)
    payload["exports"][0].pop("source_clip_id", None)
    payload["exports"][0].pop("caption_style_preset", None)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    exports = list_project_clip_exports(sample_project["project_id"])
    assert exports[0].export_kind == ExportClipKind.RAW


def test_delete_captioned_export_cleanup(sample_project, temp_backend_dirs):
    from app.services.clip_export import delete_project_clip

    exported = _export_and_caption(sample_project)

    with (
        patch(
            "app.services.video_processing._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
        patch(
            "app.services.caption_render._run_command",
            side_effect=_fake_ffmpeg_run_factory(),
        ),
    ):
        rendered = render_project_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
        )

    delete_project_clip(sample_project["project_id"], rendered.clip_id)
    exports = list_project_clip_exports(sample_project["project_id"])
    assert all(item.clip_id != rendered.clip_id for item in exports)
    assert get_clip_captions_path(sample_project["project_id"], exported.clip_id).exists()
