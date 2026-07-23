from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from pydantic import ValidationError

from app.core.config import settings
from app.models.project import (
    ProjectMetadata,
    VisualAnalysisDocument,
    VisualAnalysisStatus,
    VisualWindow,
)
from app.services.project_store import (
    get_relative_visual_analysis_path,
    get_visual_analysis_output_dir,
    get_visual_analysis_output_path,
    load_project,
    locate_video_file,
    save_project,
)
from app.services.video_processing import (
    FFmpegNotAvailableError,
    FFmpegProcessError,
    extract_sampled_grayscale_frames,
    inspect_project_video,
)

logger = logging.getLogger(__name__)


class VisualAnalysisNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class VisualAnalysisProcessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class VisualAnalysisUnavailableError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def compute_video_fingerprint(video_path: Path) -> str:
    stat = video_path.stat()
    digest = hashlib.sha256(
        f"{video_path.name}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8")
    )
    return digest.hexdigest()


def resolve_sample_interval_seconds(duration_seconds: float) -> float:
    configured = settings.visual_analysis_sample_interval_seconds
    if duration_seconds <= 0:
        return configured
    target_per_minute = settings.visual_analysis_target_samples_per_minute
    if target_per_minute <= 0:
        return configured
    derived = 60.0 / target_per_minute
    return max(configured, derived)


def _motion_between_frames(previous: bytes, current: bytes) -> float:
    if not previous or not current or len(previous) != len(current):
        return 0.0
    total = sum(abs(left - right) for left, right in zip(previous, current, strict=True))
    normalized = (total / len(previous)) / 255.0
    return round(min(10.0, normalized * 10.0 * 2.5), 2)


def _average_brightness(frame: bytes) -> float:
    if not frame:
        return 0.0
    return (sum(frame) / len(frame)) / 255.0 * 10.0


def _optional_face_count(frame: bytes, width: int, height: int) -> int | None:
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        return None

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        return None
    array = np.frombuffer(frame, dtype=np.uint8).reshape((height, width))
    faces = detector.detectMultiScale(array, scaleFactor=1.2, minNeighbors=4, minSize=(24, 24))
    return int(len(faces))


def _activity_label(score: float) -> str:
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def _build_windows(
    frames: list[tuple[float, bytes]],
    *,
    window_seconds: float,
    scene_threshold: float,
    motion_spike_threshold: float,
    frame_width: int,
    frame_height: int,
) -> list[VisualWindow]:
    if not frames:
        return []

    metrics: list[tuple[float, float, float, float, int | None]] = []
    previous = frames[0][1]
    previous_brightness = _average_brightness(previous)
    metrics.append((frames[0][0], 0.0, 0.0, previous_brightness, _optional_face_count(previous, frame_width, frame_height)))

    for timestamp, frame in frames[1:]:
        motion = _motion_between_frames(previous, frame)
        brightness = _average_brightness(frame)
        metrics.append(
            (
                timestamp,
                motion,
                abs(brightness - previous_brightness),
                brightness,
                _optional_face_count(frame, frame_width, frame_height),
            )
        )
        previous = frame
        previous_brightness = brightness

    if not metrics:
        return []

    duration_end = metrics[-1][0] + settings.visual_analysis_sample_interval_seconds
    windows: list[VisualWindow] = []
    cursor = 0.0
    while cursor < duration_end:
        window_end = cursor + window_seconds
        bucket = [item for item in metrics if cursor <= item[0] < window_end]
        if not bucket:
            cursor += window_seconds
            continue

        motion_values = [item[1] for item in bucket]
        brightness_deltas = [item[2] for item in bucket]
        face_counts = [item[4] for item in bucket if item[4] is not None]
        peak_motion = max(motion_values)
        avg_motion = sum(motion_values) / len(motion_values)
        scene_score = max(
            peak_motion,
            max(brightness_deltas) * 2.0 if brightness_deltas else 0.0,
        )
        activity_score = round(min(10.0, avg_motion * 0.55 + peak_motion * 0.45), 2)
        events: list[str] = []
        if peak_motion >= motion_spike_threshold * 25.0:
            events.append("motion_spike")
        if scene_score >= scene_threshold * 25.0:
            events.append("camera_cut")
        if activity_score <= 2.5:
            events.append("low_activity")
        if brightness_deltas and max(brightness_deltas) >= 1.5:
            events.append("brightness_change")

        peak_timestamp = bucket[motion_values.index(peak_motion)][0]
        windows.append(
            VisualWindow(
                start=round(cursor, 3),
                end=round(min(window_end, duration_end), 3),
                motion_score=round(peak_motion, 2),
                scene_change_score=round(min(10.0, scene_score), 2),
                activity_score=activity_score,
                brightness_delta=round(max(brightness_deltas) if brightness_deltas else 0.0, 2),
                face_count=max(face_counts) if face_counts else None,
                activity_label=_activity_label(activity_score),
                events=events,
                peak_motion_timestamp=round(peak_timestamp, 3),
            )
        )
        cursor += window_seconds
    return windows


def is_visual_analysis_document_current(document: VisualAnalysisDocument) -> bool:
    return document.pipeline_version == settings.visual_analysis_pipeline_version


def load_project_visual_analysis(project_id: str) -> VisualAnalysisDocument:
    output_path = get_visual_analysis_output_path(project_id)
    if not output_path.exists():
        raise VisualAnalysisNotFoundError(
            "Visual analysis not found. Run visual analysis before loading results."
        )
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        document = VisualAnalysisDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VisualAnalysisProcessError("Visual analysis file is corrupted.") from exc
    if not is_visual_analysis_document_current(document):
        raise VisualAnalysisNotFoundError(
            "Visual analysis is stale. Re-run visual analysis to refresh results."
        )
    return document


def try_load_project_visual_analysis(project_id: str) -> VisualAnalysisDocument | None:
    try:
        return load_project_visual_analysis(project_id)
    except (VisualAnalysisNotFoundError, VisualAnalysisProcessError):
        return None


def _write_visual_analysis_atomically(project_id: str, document: VisualAnalysisDocument) -> str:
    output_dir = get_visual_analysis_output_dir(project_id)
    output_path = get_visual_analysis_output_path(project_id)
    partial_path = output_dir / f"{settings.visual_analysis_output_filename}.part"
    partial_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")
    partial_path.replace(output_path)
    return get_relative_visual_analysis_path(project_id)


def analyze_project_visuals(project_id: str, *, force: bool = False) -> VisualAnalysisDocument:
    if not settings.visual_analysis_enabled:
        raise VisualAnalysisUnavailableError("Visual analysis is disabled in configuration.")

    project = load_project(project_id)
    if project.inspection_status.value != "completed":
        raise VisualAnalysisProcessError("Video inspection must be completed before visual analysis.")

    video_path = locate_video_file(project)
    fingerprint = compute_video_fingerprint(video_path)
    output_path = get_visual_analysis_output_path(project_id)

    if not force and output_path.exists():
        try:
            existing = VisualAnalysisDocument.model_validate(
                json.loads(output_path.read_text(encoding="utf-8"))
            )
            if (
                is_visual_analysis_document_current(existing)
                and existing.video_fingerprint == fingerprint
            ):
                _update_project_visual_state(
                    project_id,
                    status=VisualAnalysisStatus.COMPLETED,
                    document=existing,
                )
                return existing
        except (json.JSONDecodeError, ValidationError):
            pass

    project = load_project(project_id)
    project.visual_analysis_status = VisualAnalysisStatus.PROCESSING
    project.visual_analysis_started_at = project.updated_at
    project.last_error = None
    project.append_log("Visual analysis started.")
    save_project(project)

    started = time.perf_counter()
    metadata = project.video_metadata or inspect_project_video(project_id)
    duration = metadata.duration_seconds or 0.0
    sample_interval = resolve_sample_interval_seconds(duration)
    warnings: list[str] = []

    try:
        frames = extract_sampled_grayscale_frames(
            video_path,
            sample_interval_seconds=sample_interval,
            frame_width=settings.visual_analysis_frame_width,
            frame_height=settings.visual_analysis_frame_height,
            duration_seconds=duration or None,
        )
    except FFmpegNotAvailableError as exc:
        _mark_visual_analysis_failed(project_id, reason=exc.message)
        raise VisualAnalysisUnavailableError(exc.message) from exc
    except FFmpegProcessError as exc:
        _mark_visual_analysis_failed(project_id, reason=exc.message)
        raise VisualAnalysisProcessError(exc.message) from exc

    if not frames:
        warnings.append("No sampled frames were extracted from the source video.")

    windows = _build_windows(
        frames,
        window_seconds=settings.visual_analysis_window_seconds,
        scene_threshold=settings.visual_analysis_scene_change_threshold,
        motion_spike_threshold=settings.visual_analysis_motion_spike_threshold,
        frame_width=settings.visual_analysis_frame_width,
        frame_height=settings.visual_analysis_frame_height,
    )

    elapsed = round(time.perf_counter() - started, 3)
    document = VisualAnalysisDocument(
        project_id=project_id,
        pipeline_version=settings.visual_analysis_pipeline_version,
        video_fingerprint=fingerprint,
        processing_duration_seconds=elapsed,
        sampled_frame_count=len(frames),
        sample_interval_seconds=sample_interval,
        window_seconds=settings.visual_analysis_window_seconds,
        windows=windows,
        warnings=warnings,
    )
    _write_visual_analysis_atomically(project_id, document)
    _update_project_visual_state(
        project_id,
        status=VisualAnalysisStatus.COMPLETED,
        document=document,
    )
    return document


def mark_visual_analysis_unavailable(project_id: str, *, reason: str) -> None:
    project = load_project(project_id)
    project.visual_analysis_status = VisualAnalysisStatus.UNAVAILABLE
    project.visual_analysis_completed_at = project.updated_at
    project.last_error = reason
    project.append_log(f"Visual analysis unavailable: {reason}", level="warning")
    save_project(project)


def _mark_visual_analysis_failed(project_id: str, *, reason: str) -> None:
    project = load_project(project_id)
    project.visual_analysis_status = VisualAnalysisStatus.FAILED
    project.visual_analysis_completed_at = project.updated_at
    project.last_error = reason
    project.append_log(f"Visual analysis failed: {reason}", level="error")
    save_project(project)


def _update_project_visual_state(
    project_id: str,
    *,
    status: VisualAnalysisStatus,
    document: VisualAnalysisDocument | None = None,
    failure_reason: str | None = None,
) -> None:
    project = load_project(project_id)
    project.visual_analysis_status = status
    if document is not None:
        project.visual_analysis_path = get_relative_visual_analysis_path(project_id)
        project.visual_analysis_duration_seconds = document.processing_duration_seconds
        project.visual_analysis_sampled_frame_count = document.sampled_frame_count
        project.visual_analysis_window_count = len(document.windows)
        project.visual_analysis_completed_at = document.created_at
    if failure_reason:
        project.last_error = failure_reason
    save_project(project)


def windows_overlapping_range(
    document: VisualAnalysisDocument,
    start: float,
    end: float,
) -> list[VisualWindow]:
    return [
        window
        for window in document.windows
        if window.start < end and window.end > start
    ]


def visual_analysis_available() -> bool:
    if not settings.visual_analysis_enabled:
        return False
    try:
        from app.services.video_processing import check_ffmpeg_availability

        availability = check_ffmpeg_availability()
        return availability.ffmpeg_available
    except Exception:
        return False
