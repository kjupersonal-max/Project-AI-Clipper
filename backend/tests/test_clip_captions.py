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
    ProcessingStatus,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
    VideoMetadata,
)
from app.services.clip_captions import (
    ClipCaptionsGenerationError,
    ClipCaptionsNotFoundError,
    ClipCaptionsValidationError,
    extract_caption_segments_from_transcript,
    generate_clip_captions,
    get_clip_captions,
    reset_clip_captions,
    update_clip_captions,
)
from app.services.clip_export import ClipExportNotFoundError, export_project_clip
from app.services.project_store import (
    get_clip_captions_path,
    get_transcript_output_path,
    load_project,
    save_project,
)
from app.models.project import UpdateCaptionSegmentRequest


def _completed_process(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def _fake_ffmpeg_run_factory():
    def fake_run(command, timeout_seconds):
        if command[-1] == "-version":
            return _completed_process(command, stdout=f"{Path(command[0]).stem} version 6.0")

        if Path(command[0]).stem == "ffmpeg" and command[1:3] == ["-hide_banner", "-loglevel"]:
            output_path = Path(command[-1])
            output_path.write_bytes(b"\x00\x00\x00\x20ftypmp42")
            return _completed_process(command)

        raise AssertionError(f"Unexpected command: {command}")

    return fake_run


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


def _sample_transcript(project_id: str, *, with_words: bool = True) -> TranscriptDocument:
    words = (
        [
            TranscriptWord(word="Hello", start=0.0, end=0.8, probability=0.99),
            TranscriptWord(word="world", start=0.8, end=2.5, probability=0.98),
        ]
        if with_words
        else []
    )
    return TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=10.5,
        segment_count=3,
        word_count=4 if with_words else 0,
        segments=[
            TranscriptSegment(
                id=0,
                start=0.0,
                end=2.5,
                text="Hello world",
                words=words,
            ),
            TranscriptSegment(
                id=1,
                start=3.0,
                end=5.0,
                text="Middle segment",
                words=[
                    TranscriptWord(word="Middle", start=3.0, end=3.8, probability=0.95),
                    TranscriptWord(word="segment", start=3.8, end=5.0, probability=0.94),
                ],
            ),
            TranscriptSegment(
                id=2,
                start=8.0,
                end=10.0,
                text="Late segment",
                words=[],
            ),
        ],
    )


def _export_sample_clip(sample_project):
    _set_video_metadata(sample_project)
    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        return export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=5.0,
            clip_name="Caption Clip",
        )


def test_relative_timestamp_conversion():
    transcript = TranscriptDocument(
        project_id="project-1",
        language="en",
        duration=10.0,
        segment_count=1,
        word_count=2,
        segments=[
            TranscriptSegment(
                id=0,
                start=1.0,
                end=4.0,
                text="Hello world",
                words=[
                    TranscriptWord(word="Hello", start=1.0, end=2.0, probability=0.99),
                    TranscriptWord(word="world", start=2.0, end=4.0, probability=0.98),
                ],
            )
        ],
    )

    segments = extract_caption_segments_from_transcript(transcript, clip_start=1.0, clip_end=4.0)

    assert len(segments) == 1
    assert segments[0].start == pytest.approx(0.0)
    assert segments[0].end == pytest.approx(3.0)
    assert segments[0].words[0].start == pytest.approx(0.0)
    assert segments[0].words[0].end == pytest.approx(1.0)
    assert segments[0].words[1].start == pytest.approx(1.0)
    assert segments[0].words[1].end == pytest.approx(3.0)


def test_word_level_timing(sample_project, temp_backend_dirs):
    transcript = _sample_transcript(sample_project["project_id"], with_words=True)
    _write_transcript(sample_project["project_id"], transcript)
    _set_video_metadata(sample_project)

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        exported = export_project_clip(
            sample_project["project_id"],
            start_time=0.0,
            end_time=2.5,
            clip_name="Word Level Clip",
        )

    response = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    assert len(response.segments) == 1
    assert response.segments[0].words
    assert response.segments[0].text == "Hello world"


def test_segment_level_fallback(sample_project, temp_backend_dirs):
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
                end=4.5,
                text="Segment only text",
                words=[],
            )
        ],
    )
    _write_transcript(sample_project["project_id"], transcript)
    exported = _export_sample_clip(sample_project)

    response = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    assert len(response.segments) == 1
    assert response.segments[0].words == []
    assert response.segments[0].text == "Segment only text"
    assert response.segments[0].start == pytest.approx(0.0)
    assert response.segments[0].end == pytest.approx(3.5)


def test_caption_generation_success(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)

    response = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    assert response.project_id == sample_project["project_id"]
    assert response.clip_id == exported.clip_id
    assert response.source_start_time == pytest.approx(1.0)
    assert response.source_end_time == pytest.approx(5.0)
    assert response.duration == pytest.approx(4.0)
    assert len(response.segments) >= 1

    captions_path = get_clip_captions_path(sample_project["project_id"], exported.clip_id)
    assert captions_path.exists()


def test_no_transcript_available(sample_project, temp_backend_dirs):
    exported = _export_sample_clip(sample_project)

    with pytest.raises(ClipCaptionsGenerationError, match="No transcript available"):
        generate_clip_captions(sample_project["project_id"], exported.clip_id)


def test_invalid_clip(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))

    with pytest.raises(ClipExportNotFoundError):
        generate_clip_captions(sample_project["project_id"], str(uuid.uuid4()))


def test_invalid_caption_timing(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)
    generated = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    with pytest.raises(ClipCaptionsValidationError, match="end time must be after start"):
        update_clip_captions(
            sample_project["project_id"],
            exported.clip_id,
            [
                UpdateCaptionSegmentRequest(
                    id=generated.segments[0].id,
                    text="Bad timing",
                    start=2.0,
                    end=1.0,
                    sequence=0,
                )
            ],
        )


def test_caption_persistence(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)
    generated = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    reloaded = get_clip_captions(sample_project["project_id"], exported.clip_id)

    assert reloaded.segments[0].id == generated.segments[0].id
    assert reloaded.segments[0].text == generated.segments[0].text


def test_caption_update(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)
    generated = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    updated = update_clip_captions(
        sample_project["project_id"],
        exported.clip_id,
        [
            UpdateCaptionSegmentRequest(
                id=generated.segments[0].id,
                text="Updated caption",
                start=0.5,
                end=2.0,
                sequence=0,
            )
        ],
    )

    assert updated.segments[0].text == "Updated caption"
    assert updated.segments[0].start == pytest.approx(0.5)
    assert updated.segments[0].end == pytest.approx(2.0)


def test_caption_reset_delete(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)
    generate_clip_captions(sample_project["project_id"], exported.clip_id)

    response = reset_clip_captions(sample_project["project_id"], exported.clip_id)

    assert response.clip_id == exported.clip_id
    assert not get_clip_captions_path(sample_project["project_id"], exported.clip_id).exists()

    with pytest.raises(ClipCaptionsNotFoundError):
        get_clip_captions(sample_project["project_id"], exported.clip_id)


def test_trimmed_clip_caption_boundaries(sample_project, temp_backend_dirs):
    transcript = _sample_transcript(sample_project["project_id"])
    _write_transcript(sample_project["project_id"], transcript)
    _set_video_metadata(sample_project)

    with patch(
        "app.services.clip_export._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        parent = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=8.0,
            clip_name="Parent Clip",
        )
        from app.services.clip_export import trim_project_clip

        trimmed = trim_project_clip(
            sample_project["project_id"],
            parent.clip_id,
            start_time=3.0,
            end_time=5.5,
            clip_name="Trimmed Clip",
        )

    response = generate_clip_captions(sample_project["project_id"], trimmed.clip_id)

    assert response.source_start_time == pytest.approx(3.0)
    assert response.source_end_time == pytest.approx(5.5)
    assert response.duration == pytest.approx(2.5)
    assert len(response.segments) == 1
    assert response.segments[0].text == "Middle segment"
    assert response.segments[0].start == pytest.approx(0.0)
    assert response.segments[0].end == pytest.approx(2.0)


def test_generate_captions_endpoint(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions/generate"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["clip_id"] == exported.clip_id
    assert len(body["segments"]) >= 1


def test_get_captions_endpoint_404(sample_project, temp_backend_dirs):
    exported = _export_sample_clip(sample_project)
    client = TestClient(app)

    response = client.get(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions"
    )

    assert response.status_code == 404


def test_delete_captions_endpoint(sample_project, temp_backend_dirs):
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    exported = _export_sample_clip(sample_project)
    client = TestClient(app)

    generate_response = client.post(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions/generate"
    )
    assert generate_response.status_code == 200

    delete_response = client.delete(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions"
    )
    assert delete_response.status_code == 200

    get_response = client.get(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions"
    )
    assert get_response.status_code == 404
