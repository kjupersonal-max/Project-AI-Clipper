from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.models.project import FFmpegAvailability, VideoMetadata
from app.services.project_store import locate_video_file, load_project

_WINGET_LINKS_DIR = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
)

_resolved_ffmpeg_path: str | None = None
_resolved_ffprobe_path: str | None = None


class FFmpegNotAvailableError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class FFprobeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class FFmpegProcessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _resolve_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    winget_candidate = _WINGET_LINKS_DIR / f"{name}.exe"
    if winget_candidate.is_file():
        return str(winget_candidate.resolve())

    return None


def resolve_ffmpeg_executables() -> tuple[str | None, str | None]:
    global _resolved_ffmpeg_path, _resolved_ffprobe_path

    _resolved_ffmpeg_path = _resolve_executable("ffmpeg")
    _resolved_ffprobe_path = _resolve_executable("ffprobe")
    return _resolved_ffmpeg_path, _resolved_ffprobe_path


def _get_ffmpeg_path() -> str:
    if _resolved_ffmpeg_path is None:
        resolve_ffmpeg_executables()
    if _resolved_ffmpeg_path is None:
        raise FFmpegNotAvailableError(
            "ffmpeg was not found in PATH or the WinGet Links directory."
        )
    return _resolved_ffmpeg_path


def _get_ffprobe_path() -> str:
    if _resolved_ffprobe_path is None:
        resolve_ffmpeg_executables()
    if _resolved_ffprobe_path is None:
        raise FFmpegNotAvailableError(
            "ffprobe was not found in PATH or the WinGet Links directory."
        )
    return _resolved_ffprobe_path


def _run_command(
    command: list[str],
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        binary = command[0]
        raise FFmpegNotAvailableError(
            f"{binary} was not found in PATH. Install FFmpeg and ensure it is available."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegProcessError(
            f"Processing timed out after {timeout_seconds} seconds."
        ) from exc


def _extract_version(output: str) -> str | None:
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    return first_line or None


def check_ffmpeg_availability() -> FFmpegAvailability:
    ffmpeg_available = False
    ffprobe_available = False
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    errors: list[str] = []

    ffmpeg_path, ffprobe_path = resolve_ffmpeg_executables()
    for binary, executable_path, flag in (
        ("ffmpeg", ffmpeg_path, "-version"),
        ("ffprobe", ffprobe_path, "-version"),
    ):
        if executable_path is None:
            errors.append(f"{binary} was not found in PATH or the WinGet Links directory.")
            continue

        try:
            result = _run_command([executable_path, flag], timeout_seconds=10)
        except FFmpegNotAvailableError as exc:
            errors.append(exc.message)
            continue

        if result.returncode != 0:
            errors.append(f"{binary} is installed but returned a non-zero exit code.")
            continue

        version = _extract_version(result.stdout or result.stderr)
        if binary == "ffmpeg":
            ffmpeg_available = True
            ffmpeg_version = version
        else:
            ffprobe_available = True
            ffprobe_version = version

    error = "; ".join(errors) if errors else None
    if ffmpeg_available and ffprobe_available:
        error = None

    return FFmpegAvailability(
        ffmpeg_available=ffmpeg_available,
        ffprobe_available=ffprobe_available,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        error=error,
    )


def ensure_ffmpeg_tools() -> FFmpegAvailability:
    availability = check_ffmpeg_availability()
    if not availability.ffmpeg_available or not availability.ffprobe_available:
        detail = availability.error or "FFmpeg and ffprobe are required but not available."
        raise HTTPException(status_code=503, detail=detail)
    return availability


def _parse_fraction(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            fraction = Fraction(value)
            if fraction.denominator == 0:
                return None
            return float(fraction)
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    except (TypeError, ValueError):
        return None
    return None


def _compute_aspect_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    ratio = Fraction(width, height).limit_denominator(1000)
    return f"{ratio.numerator}:{ratio.denominator}"


def _select_stream(streams: list[dict[str, Any]], codec_type: str) -> dict[str, Any] | None:
    for stream in streams:
        if stream.get("codec_type") == codec_type:
            return stream
    return None


def _sanitize_probe_error(stderr: str) -> str:
    cleaned = stderr.strip().splitlines()
    if not cleaned:
        return "Unable to inspect the video file."
    message = cleaned[-1]
    if len(message) > 240:
        message = message[:240] + "..."
    return message


def inspect_video_file(video_path: Path) -> VideoMetadata:
    ensure_ffmpeg_tools()

    command = [
        _get_ffprobe_path(),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    result = _run_command(command, timeout_seconds=settings.ffprobe_timeout_seconds)
    if result.returncode != 0:
        raise FFprobeError(_sanitize_probe_error(result.stderr))

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FFprobeError("ffprobe returned invalid JSON output.") from exc

    streams = payload.get("streams") or []
    format_data = payload.get("format") or {}
    video_stream = _select_stream(streams, "video")
    audio_stream = _select_stream(streams, "audio")

    width = _parse_int(video_stream.get("width")) if video_stream else None
    height = _parse_int(video_stream.get("height")) if video_stream else None

    frame_rate = None
    if video_stream:
        frame_rate = _parse_fraction(video_stream.get("avg_frame_rate"))
        if frame_rate is None:
            frame_rate = _parse_fraction(video_stream.get("r_frame_rate"))

    duration_seconds = _parse_float(format_data.get("duration"))
    if duration_seconds is None and video_stream:
        duration_seconds = _parse_float(video_stream.get("duration"))

    file_size = _parse_int(format_data.get("size"))
    if file_size is None:
        try:
            file_size = video_path.stat().st_size
        except OSError:
            file_size = None

    return VideoMetadata(
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        frame_rate=frame_rate,
        video_codec=video_stream.get("codec_name") if video_stream else None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        sample_rate=_parse_int(audio_stream.get("sample_rate")) if audio_stream else None,
        audio_channels=_parse_int(audio_stream.get("channels")) if audio_stream else None,
        file_size=file_size,
        aspect_ratio=_compute_aspect_ratio(width, height),
        has_audio=audio_stream is not None,
        has_video=video_stream is not None,
    )


def inspect_project_video(project_id: str) -> VideoMetadata:
    project = load_project(project_id)
    video_path = locate_video_file(project)
    metadata = inspect_video_file(video_path)

    if not metadata.has_video and not metadata.has_audio:
        raise FFprobeError("The file does not contain readable video or audio streams.")

    return metadata


def _sanitize_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        lowered = line.lower()
        if "error" in lowered or "invalid" in lowered or "does not contain" in lowered:
            if len(line) > 240:
                return line[:240] + "..."
            return line
    return "Audio extraction failed."


def extract_audio_to_wav(
    *,
    video_path: Path,
    output_path: Path,
) -> float | None:
    ensure_ffmpeg_tools()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(".part.wav")

    if temp_output.exists():
        temp_output.unlink()

    command = [
        _get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(temp_output),
    ]

    try:
        result = _run_command(command, timeout_seconds=settings.ffmpeg_timeout_seconds)
        if result.returncode != 0:
            raise FFmpegProcessError(_sanitize_ffmpeg_error(result.stderr))

        if not temp_output.exists() or temp_output.stat().st_size == 0:
            raise FFmpegProcessError("Audio extraction produced an empty output file.")

        if output_path.exists():
            output_path.unlink()
        temp_output.replace(output_path)

        metadata = inspect_video_file(output_path)
        return metadata.duration_seconds
    except Exception:
        if temp_output.exists():
            temp_output.unlink()
        if output_path.exists() and output_path.stat().st_size == 0:
            output_path.unlink()
        raise


def extract_project_audio(project_id: str) -> tuple[str, float | None]:
    project = load_project(project_id)
    video_path = locate_video_file(project)
    metadata = inspect_video_file(video_path)

    if not metadata.has_audio:
        raise FFmpegProcessError("The uploaded video does not contain an audio track.")

    output_path = settings.audio_dir / project_id / settings.audio_output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = extract_audio_to_wav(video_path=video_path, output_path=output_path)
    relative_path = f"{project_id}/{settings.audio_output_filename}"
    return relative_path, duration


def cleanup_audio_output(project_id: str) -> None:
    audio_dir = settings.audio_dir / project_id
    if audio_dir.exists():
        shutil.rmtree(audio_dir, ignore_errors=True)
