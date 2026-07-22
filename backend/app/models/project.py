from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActivityLogEntry(BaseModel):
    timestamp: str
    level: str = "info"
    message: str


class VideoMetadata(BaseModel):
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    audio_channels: int | None = None
    file_size: int | None = None
    aspect_ratio: str | None = None
    has_audio: bool = False
    has_video: bool = False


class ProjectMetadata(BaseModel):
    project_id: str
    original_filename: str
    stored_video_path: str
    size_bytes: int
    upload_status: ProcessingStatus = ProcessingStatus.COMPLETED
    inspection_status: ProcessingStatus = ProcessingStatus.PENDING
    audio_extraction_status: ProcessingStatus = ProcessingStatus.PENDING
    video_metadata: VideoMetadata | None = None
    extracted_audio_path: str | None = None
    extracted_audio_duration_seconds: float | None = None
    activity_log: list[ActivityLogEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_error: str | None = None

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def append_log(self, message: str, level: str = "info") -> None:
        self.activity_log.append(
            ActivityLogEntry(timestamp=utc_now_iso(), level=level, message=message)
        )
        self.touch()


class ProjectResponse(BaseModel):
    project_id: str
    original_filename: str
    stored_video_path: str
    upload_status: ProcessingStatus
    inspection_status: ProcessingStatus
    audio_extraction_status: ProcessingStatus
    video_metadata: VideoMetadata | None = None
    extracted_audio_path: str | None = None
    extracted_audio_duration_seconds: float | None = None
    size_bytes: int
    activity_log: list[ActivityLogEntry]
    created_at: str
    updated_at: str
    last_error: str | None = None


class InspectResponse(BaseModel):
    project_id: str
    inspection_status: ProcessingStatus
    video_metadata: VideoMetadata
    message: str


class ExtractAudioResponse(BaseModel):
    project_id: str
    audio_extraction_status: ProcessingStatus
    extracted_audio_path: str
    duration_seconds: float | None = None
    status: str
    message: str


class FFmpegAvailability(BaseModel):
    ffmpeg_available: bool
    ffprobe_available: bool
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    error: str | None = None


def project_to_response(project: ProjectMetadata) -> ProjectResponse:
    return ProjectResponse(
        project_id=project.project_id,
        original_filename=project.original_filename,
        stored_video_path=project.stored_video_path,
        upload_status=project.upload_status,
        inspection_status=project.inspection_status,
        audio_extraction_status=project.audio_extraction_status,
        video_metadata=project.video_metadata,
        extracted_audio_path=project.extracted_audio_path,
        extracted_audio_duration_seconds=project.extracted_audio_duration_seconds,
        size_bytes=project.size_bytes,
        activity_log=project.activity_log,
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_error=project.last_error,
    )
