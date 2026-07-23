from __future__ import annotations

import logging
import threading
import traceback
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.project import (
    ExportClipKind,
    ExportClipResponse,
    ExportedClipRecord,
    ProcessingStatus,
    utc_now_iso,
)
from app.services.caption_ass import build_ass_subtitles, probe_play_resolution
from app.services.clip_captions import (
    ClipCaptionsNotFoundError,
    get_clip_captions,
)
from app.services.clip_export import (
    ClipExportNotFoundError,
    _append_export_record,
    _record_to_export_response,
    _resolve_unique_filename,
    cleanup_partial_clip_export,
    locate_exported_clip,
    sanitize_clip_name,
)
from app.services.project_store import (
    get_clips_output_dir,
    get_relative_clip_path,
    load_project,
)
from app.services.video_processing import (
    FFmpegNotAvailableError,
    _get_ffmpeg_path,
    _run_command,
    ensure_ffmpeg_tools,
    inspect_video_file,
)

logger = logging.getLogger(__name__)

_render_locks: dict[str, threading.Lock] = {}
_render_lock_guard = threading.Lock()


class CaptionRenderValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CaptionRenderInProgressError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CaptionRenderProcessError(Exception):
    def __init__(
        self,
        message: str,
        *,
        command: list[str] | None = None,
        stdout: str = "",
        stderr: str = "",
    ):
        super().__init__(message)
        self.message = message
        self.command = command or []
        self.stdout = stdout
        self.stderr = stderr


def format_caption_render_error_detail(exc: CaptionRenderProcessError) -> str:
    if not settings.expose_detailed_render_errors:
        return exc.message

    sections = [exc.message]
    if exc.command:
        sections.append(f"FFmpeg command: {' '.join(exc.command)}")
    if exc.stdout.strip():
        sections.append(f"FFmpeg stdout:\n{exc.stdout.strip()}")
    if exc.stderr.strip():
        sections.append(f"FFmpeg stderr:\n{exc.stderr.strip()}")
    return "\n\n".join(sections)


def _render_lock_key(project_id: str, clip_id: str) -> str:
    return f"{project_id}:{clip_id}"


def _acquire_render_lock(project_id: str, clip_id: str) -> threading.Lock:
    key = _render_lock_key(project_id, clip_id)
    with _render_lock_guard:
        lock = _render_locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        raise CaptionRenderInProgressError(
            "A captioned render is already in progress for this clip."
        )
    return lock


def _release_render_lock(project_id: str, clip_id: str) -> None:
    key = _render_lock_key(project_id, clip_id)
    with _render_lock_guard:
        lock = _render_locks.get(key)
        if lock and lock.locked():
            lock.release()


def _path_arg_for_ffmpeg(path: Path, work_dir: Path) -> str:
    resolved = path.resolve()
    if resolved.parent == work_dir.resolve():
        return resolved.name
    return str(resolved)


def _build_ass_filter_value(ass_path: Path, work_dir: Path) -> str:
    resolved_ass = ass_path.resolve()
    resolved_work = work_dir.resolve()
    if resolved_ass.parent == resolved_work:
        escaped_name = resolved_ass.name.replace("'", r"\'")
        if escaped_name == resolved_ass.name:
            return f"ass={escaped_name}"
        return f"ass='{escaped_name}'"

    absolute = resolved_ass.as_posix()
    if ":" in absolute:
        drive, remainder = absolute.split(":", 1)
        quoted = f"{drive}\\:{remainder}"
    else:
        quoted = absolute
    quoted = quoted.replace("'", r"\'")
    return f"ass='{quoted}'"


def _log_ffmpeg_failure(
    *,
    command: list[str],
    stdout: str,
    stderr: str,
    exc: BaseException | None = None,
) -> None:
    logger.error(
        "Caption render FFmpeg failed\nCommand: %s\nStdout: %s\nStderr: %s\nTraceback:\n%s",
        " ".join(command),
        stdout,
        stderr,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if exc is not None
        else traceback.format_exc(),
    )


def _burn_ass_subtitles(
    *,
    input_path: Path,
    ass_path: Path,
    output_path: Path,
    has_audio: bool,
) -> None:
    ensure_ffmpeg_tools()

    work_dir = output_path.parent.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(".part.mp4")

    if temp_output.exists():
        temp_output.unlink()

    ass_filter = _build_ass_filter_value(ass_path, work_dir)
    command = [
        _get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        _path_arg_for_ffmpeg(input_path, work_dir),
        "-vf",
        ass_filter,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]

    if has_audio:
        command.extend(["-c:a", "copy"])
    else:
        command.append("-an")

    command.extend(["-movflags", "+faststart", "-y", temp_output.name])

    try:
        result = _run_command(
            command,
            timeout_seconds=settings.clip_export_timeout_seconds,
            cwd=str(work_dir),
        )
        if result.returncode != 0:
            error = CaptionRenderProcessError(
                f"Caption render FFmpeg failed with exit code {result.returncode}.",
                command=command,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
            _log_ffmpeg_failure(
                command=command,
                stdout=error.stdout,
                stderr=error.stderr,
                exc=error,
            )
            raise error

        if not temp_output.exists() or temp_output.stat().st_size == 0:
            error = CaptionRenderProcessError(
                "Caption render produced an empty output file.",
                command=command,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
            _log_ffmpeg_failure(
                command=command,
                stdout=error.stdout,
                stderr=error.stderr,
                exc=error,
            )
            raise error

        if output_path.exists():
            output_path.unlink()
        temp_output.replace(output_path)
    except CaptionRenderProcessError:
        if temp_output.exists():
            temp_output.unlink()
        if output_path.exists() and output_path.stat().st_size == 0:
            output_path.unlink()
        raise
    except Exception as exc:
        _log_ffmpeg_failure(command=command, stdout="", stderr="", exc=exc)
        if temp_output.exists():
            temp_output.unlink()
        if output_path.exists() and output_path.stat().st_size == 0:
            output_path.unlink()
        raise


def render_project_clip_captions(project_id: str, source_clip_id: str) -> ExportClipResponse:
    load_project(project_id)
    source_record, source_path = locate_exported_clip(project_id, source_clip_id)

    if source_record.export_kind == ExportClipKind.CAPTIONED:
        raise CaptionRenderValidationError(
            "Captioned exports cannot be re-rendered. Use the original clip instead."
        )

    try:
        captions = get_clip_captions(project_id, source_clip_id)
    except ClipCaptionsNotFoundError as exc:
        raise CaptionRenderValidationError(
            "Captions are required before rendering a captioned export."
        ) from exc

    if not captions.segments:
        raise CaptionRenderValidationError("Cannot render captions for an empty caption list.")

    lock = _acquire_render_lock(project_id, source_clip_id)
    original_source_size = source_path.stat().st_size
    original_source_name = source_record.filename

    clip_id = str(uuid.uuid4())
    parent_label = source_record.clip_name or source_record.filename.replace(".mp4", "")
    clip_name = f"{parent_label} (captioned)"
    sanitized_name = sanitize_clip_name(clip_name)
    clips_dir = get_clips_output_dir(project_id)
    filename = _resolve_unique_filename(clips_dir, sanitized_name)
    output_path = clips_dir / filename
    relative_path = get_relative_clip_path(project_id, filename)

    temp_ass = output_path.with_suffix(".part.ass")

    try:
        metadata = inspect_video_file(source_path)
        play_res_x, play_res_y = probe_play_resolution(metadata.width, metadata.height)
        ass_content = build_ass_subtitles(
            captions.segments,
            captions.style,
            play_res_x=play_res_x,
            play_res_y=play_res_y,
        )
        temp_ass.write_text(ass_content, encoding="utf-8")

        _burn_ass_subtitles(
            input_path=source_path,
            ass_path=temp_ass,
            output_path=output_path,
            has_audio=metadata.has_audio,
        )

        _, reloaded_source_path = locate_exported_clip(project_id, source_clip_id)
        if (
            reloaded_source_path.stat().st_size != original_source_size
            or reloaded_source_path.name != original_source_name
        ):
            cleanup_partial_clip_export(output_path)
            raise CaptionRenderProcessError(
                "Source clip was modified unexpectedly during captioned render."
            )

        file_size_bytes = output_path.stat().st_size
        created_at = utc_now_iso()
        style_preset = captions.style.preset_id.value

        record = ExportedClipRecord(
            clip_id=clip_id,
            project_id=project_id,
            filename=filename,
            relative_path=relative_path,
            start_time=source_record.start_time,
            end_time=source_record.end_time,
            duration=source_record.duration,
            file_size_bytes=file_size_bytes,
            candidate_id=source_record.candidate_id,
            clip_name=clip_name,
            created_at=created_at,
            export_status=ProcessingStatus.COMPLETED,
            export_kind=ExportClipKind.CAPTIONED,
            source_clip_id=source_clip_id,
            caption_style_preset=style_preset,
        )
        _append_export_record(record)

        return _record_to_export_response(project_id, record)
    except FFmpegNotAvailableError:
        cleanup_partial_clip_export(output_path)
        raise
    except CaptionRenderProcessError:
        cleanup_partial_clip_export(output_path)
        raise
    except Exception as exc:
        cleanup_partial_clip_export(output_path)
        _log_ffmpeg_failure(command=[], stdout="", stderr="", exc=exc)
        raise
    finally:
        if temp_ass.exists():
            temp_ass.unlink()
        _release_render_lock(project_id, source_clip_id)
