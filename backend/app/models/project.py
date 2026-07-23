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
    transcription_status: ProcessingStatus = ProcessingStatus.PENDING
    video_metadata: VideoMetadata | None = None
    extracted_audio_path: str | None = None
    extracted_audio_duration_seconds: float | None = None
    transcript_path: str | None = None
    detected_language: str | None = None
    transcription_started_at: str | None = None
    transcription_completed_at: str | None = None
    analysis_status: ProcessingStatus = ProcessingStatus.PENDING
    analysis_path: str | None = None
    analysis_started_at: str | None = None
    analysis_completed_at: str | None = None
    analysis_provider: str | None = None
    clip_selection_status: ProcessingStatus = ProcessingStatus.PENDING
    clip_candidates_path: str | None = None
    clip_selection_started_at: str | None = None
    clip_selection_completed_at: str | None = None
    clip_candidate_count: int | None = None
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
    transcription_status: ProcessingStatus
    video_metadata: VideoMetadata | None = None
    extracted_audio_path: str | None = None
    extracted_audio_duration_seconds: float | None = None
    transcript_path: str | None = None
    detected_language: str | None = None
    transcription_started_at: str | None = None
    transcription_completed_at: str | None = None
    analysis_status: ProcessingStatus
    analysis_path: str | None = None
    analysis_started_at: str | None = None
    analysis_completed_at: str | None = None
    analysis_provider: str | None = None
    clip_selection_status: ProcessingStatus
    clip_candidates_path: str | None = None
    clip_selection_started_at: str | None = None
    clip_selection_completed_at: str | None = None
    clip_candidate_count: int | None = None
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


class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class TranscriptDocument(BaseModel):
    project_id: str
    language: str
    duration: float
    segment_count: int
    word_count: int
    segments: list[TranscriptSegment]
    created_at: str = Field(default_factory=utc_now_iso)


class TranscribeResponse(BaseModel):
    project_id: str
    status: str
    language: str
    duration: float
    segment_count: int
    word_count: int
    transcript_path: str


class SegmentAnalysis(BaseModel):
    segment_id: int
    start: float
    end: float
    text: str
    emotion: str
    excitement_score: float = Field(ge=0.0, le=10.0)
    humor_score: float = Field(ge=0.0, le=10.0)
    suspense_score: float = Field(ge=0.0, le=10.0)
    educational_score: float = Field(ge=0.0, le=10.0)
    standalone_score: float = Field(ge=0.0, le=10.0)
    context_dependency_score: float = Field(ge=0.0, le=10.0)
    clip_candidate: bool
    reason: str


class AnalysisDocument(BaseModel):
    project_id: str
    provider: str
    model: str | None = None
    is_heuristic_fallback: bool = False
    segment_count: int
    clip_candidate_count: int
    segments: list[SegmentAnalysis]
    created_at: str = Field(default_factory=utc_now_iso)


class AnalyzeResponse(BaseModel):
    project_id: str
    status: str
    provider: str
    model: str | None = None
    is_heuristic_fallback: bool = False
    segment_count: int
    clip_candidate_count: int
    analysis_path: str


class ClipCandidateStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClipCandidate(BaseModel):
    clip_id: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    duration: float = Field(gt=0.0)
    segment_ids: list[int]
    transcript_text: str
    score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    primary_emotion: str
    hook_score: float = Field(ge=0.0, le=10.0)
    payoff_score: float = Field(ge=0.0, le=10.0)
    standalone_score: float = Field(ge=0.0, le=10.0)
    context_dependency_score: float = Field(ge=0.0, le=10.0)
    title_suggestion: str
    reason: str
    status: ClipCandidateStatus = ClipCandidateStatus.PROPOSED


class ClipCandidatesDocument(BaseModel):
    project_id: str
    candidate_count: int
    min_duration_seconds: float
    max_duration_seconds: float
    max_gap_seconds: float
    max_candidates: int
    source_duration_seconds: float
    candidates: list[ClipCandidate]
    created_at: str = Field(default_factory=utc_now_iso)


class SelectClipsRequest(BaseModel):
    min_duration_seconds: float | None = None
    max_duration_seconds: float | None = None
    max_gap_seconds: float | None = None
    max_candidates: int | None = None
    min_score: float | None = None


class SelectClipsResponse(BaseModel):
    project_id: str
    status: str
    candidate_count: int
    clip_candidates_path: str


class FFmpegAvailability(BaseModel):
    ffmpeg_available: bool
    ffprobe_available: bool
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    error: str | None = None


class ExportClipRequest(BaseModel):
    start_time: float = Field(ge=0.0)
    end_time: float = Field(gt=0.0)
    clip_name: str | None = None
    candidate_id: str | None = None


class RenameClipRequest(BaseModel):
    clip_name: str


class FavoriteClipRequest(BaseModel):
    is_favorite: bool


class TrimClipRequest(BaseModel):
    start_time: float = Field(ge=0.0)
    end_time: float = Field(gt=0.0)
    clip_name: str | None = None


class DeleteClipResponse(BaseModel):
    project_id: str
    clip_id: str
    message: str


class ExportClipResponse(BaseModel):
    clip_id: str
    project_id: str
    filename: str
    relative_path: str
    media_url: str
    start_time: float
    end_time: float
    duration: float
    file_size_bytes: int
    candidate_id: str | None = None
    clip_name: str | None = None
    created_at: str
    export_status: ProcessingStatus
    is_favorite: bool = False


class ExportedClipRecord(BaseModel):
    clip_id: str
    project_id: str
    filename: str
    relative_path: str
    start_time: float
    end_time: float
    duration: float
    file_size_bytes: int
    candidate_id: str | None = None
    clip_name: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    export_status: ProcessingStatus = ProcessingStatus.COMPLETED
    is_favorite: bool = False


class ClipExportsDocument(BaseModel):
    project_id: str
    exports: list[ExportedClipRecord] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


class ClipExportsListResponse(BaseModel):
    project_id: str
    exports: list[ExportClipResponse] = Field(default_factory=list)


class CaptionStylePresetId(str, Enum):
    CLEAN_MINIMAL = "clean-minimal"
    BOLD_POP = "bold-pop"
    PODCAST = "podcast"
    KARAOKE_HIGHLIGHT = "karaoke-highlight"
    HIGH_CONTRAST = "high-contrast"
    CREATOR_SUBTITLE = "creator-subtitle"
    CUSTOM = "custom"


class CaptionTextAlignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class CaptionTextTransform(str, Enum):
    NONE = "none"
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"


class CaptionAnimationType(str, Enum):
    NONE = "none"
    FADE = "fade"
    POP = "pop"
    SCALE = "scale"
    SLIDE_UP = "slide-up"
    BOUNCE = "bounce"
    ACTIVE_WORD_EMPHASIS = "active-word-emphasis"


class CaptionWordsPerGroup(str, Enum):
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FULL = "full"


class CaptionSafeAreaMode(str, Enum):
    NONE = "none"
    TIKTOK = "tiktok"
    YOUTUBE_SHORTS = "youtube-shorts"
    GENERIC = "generic"


class CaptionStyle(BaseModel):
    preset_id: CaptionStylePresetId = CaptionStylePresetId.CLEAN_MINIMAL
    font_family: str = "Inter, system-ui, sans-serif"
    font_size: float = Field(default=22.0, ge=12.0, le=72.0)
    font_weight: int = Field(default=600, ge=100, le=900)
    text_color: str = "#FFFFFF"
    active_word_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = Field(default=1.0, ge=0.0, le=8.0)
    background_color: str = "#000000"
    background_opacity: float = Field(default=0.45, ge=0.0, le=1.0)
    shadow_enabled: bool = False
    shadow_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    text_alignment: CaptionTextAlignment = CaptionTextAlignment.CENTER
    horizontal_position: float = Field(default=50.0, ge=0.0, le=100.0)
    vertical_position: float = Field(default=88.0, ge=0.0, le=100.0)
    max_line_width: float = Field(default=85.0, ge=50.0, le=100.0)
    words_per_group: CaptionWordsPerGroup = CaptionWordsPerGroup.FULL
    text_transform: CaptionTextTransform = CaptionTextTransform.NONE
    animation_type: CaptionAnimationType = CaptionAnimationType.FADE
    animation_intensity: float = Field(default=0.4, ge=0.0, le=1.0)
    safe_area_mode: CaptionSafeAreaMode = CaptionSafeAreaMode.NONE


class CaptionWord(BaseModel):
    word: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)


class CaptionSegment(BaseModel):
    id: str
    text: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    words: list[CaptionWord] = Field(default_factory=list)
    sequence: int = Field(ge=0)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ClipCaptionsDocument(BaseModel):
    project_id: str
    clip_id: str
    source_start_time: float = Field(ge=0.0)
    source_end_time: float = Field(gt=0.0)
    duration: float = Field(gt=0.0)
    candidate_id: str | None = None
    segments: list[CaptionSegment] = Field(default_factory=list)
    style: CaptionStyle | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ClipCaptionsResponse(BaseModel):
    project_id: str
    clip_id: str
    source_start_time: float
    source_end_time: float
    duration: float
    candidate_id: str | None = None
    segments: list[CaptionSegment] = Field(default_factory=list)
    style: CaptionStyle
    created_at: str
    updated_at: str


class UpdateCaptionSegmentRequest(BaseModel):
    id: str
    text: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    words: list[CaptionWord] = Field(default_factory=list)
    sequence: int = Field(ge=0)


class UpdateCaptionsRequest(BaseModel):
    segments: list[UpdateCaptionSegmentRequest]


class UpdateCaptionStyleRequest(BaseModel):
    style: CaptionStyle


class DeleteCaptionsResponse(BaseModel):
    project_id: str
    clip_id: str
    message: str


def project_to_response(project: ProjectMetadata) -> ProjectResponse:
    return ProjectResponse(
        project_id=project.project_id,
        original_filename=project.original_filename,
        stored_video_path=project.stored_video_path,
        upload_status=project.upload_status,
        inspection_status=project.inspection_status,
        audio_extraction_status=project.audio_extraction_status,
        transcription_status=project.transcription_status,
        video_metadata=project.video_metadata,
        extracted_audio_path=project.extracted_audio_path,
        extracted_audio_duration_seconds=project.extracted_audio_duration_seconds,
        transcript_path=project.transcript_path,
        detected_language=project.detected_language,
        transcription_started_at=project.transcription_started_at,
        transcription_completed_at=project.transcription_completed_at,
        analysis_status=project.analysis_status,
        analysis_path=project.analysis_path,
        analysis_started_at=project.analysis_started_at,
        analysis_completed_at=project.analysis_completed_at,
        analysis_provider=project.analysis_provider,
        clip_selection_status=project.clip_selection_status,
        clip_candidates_path=project.clip_candidates_path,
        clip_selection_started_at=project.clip_selection_started_at,
        clip_selection_completed_at=project.clip_selection_completed_at,
        clip_candidate_count=project.clip_candidate_count,
        size_bytes=project.size_bytes,
        activity_log=project.activity_log,
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_error=project.last_error,
    )
