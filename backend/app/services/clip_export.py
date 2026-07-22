from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings
from app.models.project import (
    ClipExportsDocument,
    ExportClipResponse,
    ExportedClipRecord,
    ProcessingStatus,
    utc_now_iso,
)
from app.services.clip_selection import (
    ClipCandidatesNotFoundError,
    load_project_clip_candidates,
)
from app.services.project_store import (
    get_clip_exports_manifest_path,
    get_clips_output_dir,
    get_relative_clip_path,
    load_project,
    locate_video_file,
)
from app.services.video_processing import (
    FFmpegNotAvailableError,
    FFmpegProcessError,
    _get_ffmpeg_path,
    _run_command,
    _sanitize_ffmpeg_error,
    ensure_ffmpeg_tools,
    inspect_video_file,
)


class ClipExportValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipExportNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ClipExportProcessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def sanitize_clip_name(name: str) -> str:
    safe = re.sub(r"[^\w.\- ]+", "", name.strip(), flags=re.UNICODE)
    safe = re.sub(r"\s+", "_", safe.strip("._ "))
    safe = safe[:200] or "clip"
    return safe


def _resolve_unique_filename(clips_dir: Path, base_name: str) -> str:
    candidate = f"{base_name}.mp4"
    if not (clips_dir / candidate).exists():
        return candidate

    counter = 2
    while (clips_dir / f"{base_name}_{counter}.mp4").exists():
        counter += 1
    return f"{base_name}_{counter}.mp4"


def _get_source_duration_seconds(project_id: str, video_path: Path) -> float:
    project = load_project(project_id)
    if project.video_metadata and project.video_metadata.duration_seconds is not None:
        return project.video_metadata.duration_seconds

    metadata = inspect_video_file(video_path)
    if metadata.duration_seconds is None:
        raise ClipExportValidationError("Unable to determine source video duration.")
    return metadata.duration_seconds


def _validate_export_times(
    *,
    start_time: float,
    end_time: float,
    source_duration: float,
) -> float:
    if start_time < 0:
        raise ClipExportValidationError("start_time must be greater than or equal to 0.")

    if end_time <= start_time:
        raise ClipExportValidationError("end_time must be greater than start_time.")

    if end_time > source_duration:
        raise ClipExportValidationError(
            f"end_time ({end_time:.3f}s) exceeds source video duration ({source_duration:.3f}s)."
        )

    duration = end_time - start_time
    if duration > settings.clip_export_max_duration_seconds:
        raise ClipExportValidationError(
            f"Clip duration ({duration:.3f}s) exceeds the maximum allowed "
            f"({settings.clip_export_max_duration_seconds:.3f}s)."
        )

    return duration


def _validate_candidate_id(project_id: str, candidate_id: str | None) -> None:
    if candidate_id is None:
        return

    try:
        document = load_project_clip_candidates(project_id)
    except ClipCandidatesNotFoundError as exc:
        raise ClipExportValidationError(exc.message) from exc

    if not any(candidate.clip_id == candidate_id for candidate in document.candidates):
        raise ClipExportValidationError(f"Clip candidate '{candidate_id}' was not found.")


def _record_to_export_response(
    project_id: str,
    record: ExportedClipRecord,
) -> ExportClipResponse:
    return ExportClipResponse(
        clip_id=record.clip_id,
        project_id=record.project_id,
        filename=record.filename,
        relative_path=record.relative_path,
        media_url=f"/api/projects/{project_id}/media/clips/{record.clip_id}",
        start_time=record.start_time,
        end_time=record.end_time,
        duration=record.duration,
        file_size_bytes=record.file_size_bytes,
        candidate_id=record.candidate_id,
        clip_name=record.clip_name,
        created_at=record.created_at,
        export_status=record.export_status,
    )


def _parse_export_record(raw: object, project_id: str) -> ExportedClipRecord | None:
    if not isinstance(raw, dict):
        return None

    try:
        record = ExportedClipRecord.model_validate(raw)
    except ValueError:
        return None

    if record.project_id != project_id:
        return None

    return record


def _load_exports_manifest_records(project_id: str) -> list[ExportedClipRecord]:
    manifest_path = get_clip_exports_manifest_path(project_id)
    if not manifest_path.exists():
        return []

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, dict):
        return []

    exports_raw = payload.get("exports", [])
    if not isinstance(exports_raw, list):
        return []

    records: list[ExportedClipRecord] = []
    for item in exports_raw:
        record = _parse_export_record(item, project_id)
        if record is not None:
            records.append(record)
    return records


def list_project_clip_exports(project_id: str) -> list[ExportClipResponse]:
    load_project(project_id)

    clips_dir = get_clips_output_dir(project_id)
    records = _load_exports_manifest_records(project_id)
    responses: list[ExportClipResponse] = []

    for record in records:
        if record.export_status != ProcessingStatus.COMPLETED:
            continue

        clip_path = clips_dir / record.filename
        if not clip_path.is_file() or clip_path.stat().st_size == 0:
            continue

        responses.append(_record_to_export_response(project_id, record))

    responses.sort(key=lambda export: export.created_at, reverse=True)
    return responses


def _load_exports_document(project_id: str) -> ClipExportsDocument:
    manifest_path = get_clip_exports_manifest_path(project_id)
    if not manifest_path.exists():
        return ClipExportsDocument(project_id=project_id)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return ClipExportsDocument.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ClipExportProcessError("Clip export manifest is corrupted.") from exc


def _write_exports_document(document: ClipExportsDocument) -> None:
    manifest_path = get_clip_exports_manifest_path(document.project_id)
    partial_path = manifest_path.with_suffix(".part.json")
    document.updated_at = utc_now_iso()
    partial_path.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    partial_path.replace(manifest_path)


def _append_export_record(record: ExportedClipRecord) -> None:
    document = _load_exports_document(record.project_id)
    document.exports.append(record)
    _write_exports_document(document)


def _export_video_segment_to_mp4(
    *,
    video_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    has_audio: bool,
) -> None:
    ensure_ffmpeg_tools()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(".part.mp4")

    if temp_output.exists():
        temp_output.unlink()

    command = [
        _get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-ss",
        f"{start_time:.6f}",
        "-to",
        f"{end_time:.6f}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]

    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        command.append("-an")

    command.extend(["-movflags", "+faststart", "-y", str(temp_output)])

    try:
        result = _run_command(command, timeout_seconds=settings.clip_export_timeout_seconds)
        if result.returncode != 0:
            raise FFmpegProcessError(_sanitize_ffmpeg_error(result.stderr))

        if not temp_output.exists() or temp_output.stat().st_size == 0:
            raise FFmpegProcessError("Clip export produced an empty output file.")

        if output_path.exists():
            output_path.unlink()
        temp_output.replace(output_path)
    except Exception:
        if temp_output.exists():
            temp_output.unlink()
        if output_path.exists() and output_path.stat().st_size == 0:
            output_path.unlink()
        raise


def cleanup_partial_clip_export(output_path: Path) -> None:
    partial_path = output_path.with_suffix(".part.mp4")
    if partial_path.exists():
        partial_path.unlink()
    if output_path.exists():
        output_path.unlink()


def export_project_clip(
    project_id: str,
    *,
    start_time: float,
    end_time: float,
    clip_name: str | None = None,
    candidate_id: str | None = None,
) -> ExportClipResponse:
    project = load_project(project_id)
    video_path = locate_video_file(project)

    _validate_candidate_id(project_id, candidate_id)

    source_duration = _get_source_duration_seconds(project_id, video_path)
    duration = _validate_export_times(
        start_time=start_time,
        end_time=end_time,
        source_duration=source_duration,
    )

    source_metadata = project.video_metadata
    if source_metadata is None:
        source_metadata = inspect_video_file(video_path)

    clip_id = str(uuid.uuid4())
    sanitized_name = sanitize_clip_name(clip_name) if clip_name else f"clip_{clip_id[:8]}"
    clips_dir = get_clips_output_dir(project_id)
    filename = _resolve_unique_filename(clips_dir, sanitized_name)
    output_path = clips_dir / filename
    relative_path = get_relative_clip_path(project_id, filename)

    try:
        _export_video_segment_to_mp4(
            video_path=video_path,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            has_audio=source_metadata.has_audio,
        )
    except FFmpegNotAvailableError as exc:
        cleanup_partial_clip_export(output_path)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except FFmpegProcessError as exc:
        cleanup_partial_clip_export(output_path)
        raise ClipExportProcessError(exc.message) from exc

    file_size_bytes = output_path.stat().st_size
    created_at = utc_now_iso()

    record = ExportedClipRecord(
        clip_id=clip_id,
        project_id=project_id,
        filename=filename,
        relative_path=relative_path,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        file_size_bytes=file_size_bytes,
        candidate_id=candidate_id,
        clip_name=clip_name,
        created_at=created_at,
        export_status=ProcessingStatus.COMPLETED,
    )
    _append_export_record(record)

    return _record_to_export_response(project_id, record)


def _find_export_record(document: ClipExportsDocument, clip_id: str) -> ExportedClipRecord:
    record = next((export for export in document.exports if export.clip_id == clip_id), None)
    if record is None:
        raise ClipExportNotFoundError(f"Exported clip '{clip_id}' was not found.")
    return record


def locate_exported_clip(project_id: str, clip_id: str) -> tuple[ExportedClipRecord, Path]:
    document = _load_exports_document(project_id)
    record = _find_export_record(document, clip_id)

    clips_dir = get_clips_output_dir(project_id)
    clip_path = clips_dir / record.filename
    if not clip_path.exists() or not clip_path.is_file():
        raise ClipExportNotFoundError(f"Exported clip file for '{clip_id}' was not found.")

    return record, clip_path


def rename_project_clip(project_id: str, clip_id: str, *, clip_name: str) -> ExportClipResponse:
    load_project(project_id)

    trimmed_name = clip_name.strip()
    if not trimmed_name:
        raise ClipExportValidationError("clip_name must not be empty.")

    document = _load_exports_document(project_id)
    record = _find_export_record(document, clip_id)
    record.clip_name = trimmed_name
    _write_exports_document(document)

    return _record_to_export_response(project_id, record)


def delete_project_clip(project_id: str, clip_id: str) -> ExportedClipRecord:
    load_project(project_id)

    document = _load_exports_document(project_id)
    record = _find_export_record(document, clip_id)

    clips_dir = get_clips_output_dir(project_id)
    clip_path = clips_dir / record.filename
    if clip_path.exists() and clip_path.is_file():
        clip_path.unlink()

    document.exports = [export for export in document.exports if export.clip_id != clip_id]
    _write_exports_document(document)

    return record
