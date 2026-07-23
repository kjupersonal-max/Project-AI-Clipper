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


class TranscriptTier(str, Enum):
    LEGACY = "legacy"
    DISCOVERY = "discovery"
    FULL_QUALITY = "full_quality"
    CLIP_QUALITY = "clip_quality"


class ChunkProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"


class PipelineStage(str, Enum):
    DISCOVERY_TRANSCRIPTION = "discovery_transcription"
    DISCOVERY_CHUNK = "discovery_chunk"
    CHUNK_ANALYSIS = "chunk_analysis"
    CANDIDATE_GENERATION = "candidate_generation"
    GLOBAL_RANKING = "global_ranking"
    CLIP_RETRANSCRIPTION = "clip_retranscription"
    FINAL_CAPTION_READY = "final_caption_ready"


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
    discovery_transcript_path: str | None = None
    active_transcript_tier: TranscriptTier | None = None
    detected_language: str | None = None
    transcription_started_at: str | None = None
    transcription_completed_at: str | None = None
    transcription_quality_mode: str | None = None
    transcription_stage: str | None = None
    transcription_progress_pct: float | None = None
    discovery_transcription_status: ProcessingStatus = ProcessingStatus.PENDING
    discovery_transcription_stage: str | None = None
    discovery_transcription_progress_pct: float | None = None
    discovery_chunks_completed: int | None = None
    discovery_chunks_total: int | None = None
    discovery_chunks_remaining: int | None = None
    pipeline_stage: str | None = None
    clip_retranscription_status: ProcessingStatus = ProcessingStatus.PENDING
    clip_retranscription_progress_pct: float | None = None
    vocabulary_hints: str | None = None
    analysis_status: ProcessingStatus = ProcessingStatus.PENDING
    analysis_path: str | None = None
    analysis_stage: str | None = None
    analysis_progress_pct: float | None = None
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
    discovery_transcript_path: str | None = None
    active_transcript_tier: TranscriptTier | None = None
    detected_language: str | None = None
    transcription_started_at: str | None = None
    transcription_completed_at: str | None = None
    transcription_quality_mode: str | None = None
    transcription_stage: str | None = None
    transcription_progress_pct: float | None = None
    discovery_transcription_status: ProcessingStatus = ProcessingStatus.PENDING
    discovery_transcription_stage: str | None = None
    discovery_transcription_progress_pct: float | None = None
    discovery_chunks_completed: int | None = None
    discovery_chunks_total: int | None = None
    discovery_chunks_remaining: int | None = None
    pipeline_stage: str | None = None
    clip_retranscription_status: ProcessingStatus = ProcessingStatus.PENDING
    clip_retranscription_progress_pct: float | None = None
    vocabulary_hints: str | None = None
    analysis_status: ProcessingStatus
    analysis_path: str | None = None
    analysis_stage: str | None = None
    analysis_progress_pct: float | None = None
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


class TranscriptionQualityRating(str, Enum):
    GOOD = "good"
    REVIEW_RECOMMENDED = "review_recommended"
    POOR = "poor"


class TranscriptionQualityMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH_ACCURACY = "high_accuracy"


class TranscriptDocument(BaseModel):
    project_id: str
    language: str
    duration: float
    segment_count: int
    word_count: int
    segments: list[TranscriptSegment]
    created_at: str = Field(default_factory=utc_now_iso)
    quality_mode: TranscriptionQualityMode | None = None
    quality_rating: TranscriptionQualityRating | None = None
    quality_warnings: list[str] = Field(default_factory=list)
    vocabulary_hints: str | None = None
    transcription_revision: int = 1
    transcript_tier: TranscriptTier = TranscriptTier.LEGACY
    chunk_index: int | None = None
    chunk_start: float | None = None
    chunk_end: float | None = None
    clip_id: str | None = None
    candidate_id: str | None = None


class TranscribeRequest(BaseModel):
    quality_mode: TranscriptionQualityMode | None = None
    vocabulary_hints: str | None = None
    preserve_manual_edits: bool = False
    use_full_quality: bool = False


class TranscribeResponse(BaseModel):
    project_id: str
    status: str
    language: str
    duration: float
    segment_count: int
    word_count: int
    transcript_path: str
    transcript_tier: TranscriptTier | None = None
    quality_mode: TranscriptionQualityMode | None = None
    quality_rating: TranscriptionQualityRating | None = None
    warnings: list[str] = Field(default_factory=list)


class TranscriptionDiagnosticsRequest(BaseModel):
    quality_mode: TranscriptionQualityMode | None = None
    vocabulary_hints: str | None = None
    language: str | None = None
    clip_start: float | None = None
    clip_end: float | None = None


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


class ImportanceBreakdown(BaseModel):
    hook: float = Field(ge=0.0, le=10.0)
    emotion: float = Field(ge=0.0, le=10.0)
    story_value: float = Field(ge=0.0, le=10.0)
    information_value: float = Field(ge=0.0, le=10.0)
    retention: float = Field(ge=0.0, le=10.0)
    shareability: float = Field(ge=0.0, le=10.0)
    standalone_quality: float = Field(ge=0.0, le=10.0)
    monetization_potential: float = Field(ge=0.0, le=10.0)


class VisualSignalScores(BaseModel):
    face_presence: float | None = Field(default=None, ge=0.0, le=10.0)
    facial_reaction: float | None = Field(default=None, ge=0.0, le=10.0)
    motion_spike: float | None = Field(default=None, ge=0.0, le=10.0)
    scene_change: float | None = Field(default=None, ge=0.0, le=10.0)
    person_entering: float | None = Field(default=None, ge=0.0, le=10.0)
    person_leaving: float | None = Field(default=None, ge=0.0, le=10.0)
    hiding: float | None = Field(default=None, ge=0.0, le=10.0)
    fear: float | None = Field(default=None, ge=0.0, le=10.0)
    laughter: float | None = Field(default=None, ge=0.0, le=10.0)
    physical_action: float | None = Field(default=None, ge=0.0, le=10.0)
    object_reveal: float | None = Field(default=None, ge=0.0, le=10.0)


class VisualEvidence(BaseModel):
    provider: str | None = None
    model: str | None = None
    signals: VisualSignalScores = Field(default_factory=VisualSignalScores)
    notes: list[str] = Field(default_factory=list)


class RejectedClipCandidate(BaseModel):
    clip_id: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    duration: float = Field(gt=0.0)
    score: float = Field(ge=0.0, le=100.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    importance_breakdown: ImportanceBreakdown | None = None
    reason: str = ""
    rejection_reason: str


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
    warnings: list[str] = Field(default_factory=list)
    duration_exception_reason: str | None = None
    duration_class: str | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    importance_breakdown: ImportanceBreakdown | None = None
    selection_reasons: list[str] = Field(default_factory=list)
    visual_evidence: VisualEvidence | None = None


class ClipCandidatesDocument(BaseModel):
    project_id: str
    candidate_count: int
    min_duration_seconds: float
    max_duration_seconds: float
    max_gap_seconds: float
    max_candidates: int
    source_duration_seconds: float
    candidates: list[ClipCandidate]
    rejected_candidates: list[RejectedClipCandidate] = Field(default_factory=list)
    quality_threshold: float | None = None
    selection_pipeline_version: str | None = None
    analysis_pipeline_version: str | None = None
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


class ExportClipKind(str, Enum):
    RAW = "raw"
    CAPTIONED = "captioned"


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
    export_kind: ExportClipKind = ExportClipKind.RAW
    source_clip_id: str | None = None
    caption_style_preset: str | None = None


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
    export_kind: ExportClipKind = ExportClipKind.RAW
    source_clip_id: str | None = None
    caption_style_preset: str | None = None


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
    manually_edited: bool = False
    original_transcription_text: str | None = None
    transcription_revision: int | None = None
    low_confidence: bool = False
    overlapping_speech: bool = False


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
    transcription_quality_mode: TranscriptionQualityMode | None = None
    transcription_quality_rating: TranscriptionQualityRating | None = None
    transcription_warnings: list[str] = Field(default_factory=list)
    vocabulary_hints: str | None = None


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
    transcription_quality_mode: TranscriptionQualityMode | None = None
    transcription_quality_rating: TranscriptionQualityRating | None = None
    transcription_warnings: list[str] = Field(default_factory=list)
    vocabulary_hints: str | None = None


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


class RetranscribeRangeRequest(BaseModel):
    start_time: float = Field(ge=0.0)
    end_time: float = Field(gt=0.0)
    quality_mode: TranscriptionQualityMode | None = None
    vocabulary_hints: str | None = None


class RetranscribeRangePreviewResponse(BaseModel):
    project_id: str
    clip_id: str
    start_time: float
    end_time: float
    preview_segments: list[CaptionSegment]
    quality_rating: TranscriptionQualityRating | None = None
    warnings: list[str] = Field(default_factory=list)
    manual_edit_warnings: list[str] = Field(default_factory=list)


class ApplyRetranscribeRangeRequest(BaseModel):
    start_time: float = Field(ge=0.0)
    end_time: float = Field(gt=0.0)
    preview_segments: list[UpdateCaptionSegmentRequest]
    mode: str = "replace"


class InsertCaptionWordRequest(BaseModel):
    segment_id: str
    word: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)


class InsertCaptionSegmentRequest(BaseModel):
    text: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)


class SplitCaptionSegmentRequest(BaseModel):
    segment_id: str
    split_time: float = Field(ge=0.0)


class MergeCaptionSegmentsRequest(BaseModel):
    first_segment_id: str
    second_segment_id: str


class NudgeCaptionTimingRequest(BaseModel):
    segment_id: str
    delta_seconds: float


class DeleteCaptionWordRequest(BaseModel):
    segment_id: str
    word_index: int = Field(ge=0)


class UpdateVocabularyHintsRequest(BaseModel):
    vocabulary_hints: str | None = None


class TranscriptionQualityResponse(BaseModel):
    project_id: str
    clip_id: str | None = None
    quality_mode: TranscriptionQualityMode | None = None
    quality_rating: TranscriptionQualityRating | None = None
    warnings: list[str] = Field(default_factory=list)
    manual_edit_count: int = 0


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
        discovery_transcript_path=project.discovery_transcript_path,
        active_transcript_tier=project.active_transcript_tier,
        detected_language=project.detected_language,
        transcription_started_at=project.transcription_started_at,
        transcription_completed_at=project.transcription_completed_at,
        transcription_quality_mode=project.transcription_quality_mode,
        transcription_stage=project.transcription_stage,
        transcription_progress_pct=project.transcription_progress_pct,
        discovery_transcription_status=project.discovery_transcription_status,
        discovery_transcription_stage=project.discovery_transcription_stage,
        discovery_transcription_progress_pct=project.discovery_transcription_progress_pct,
        discovery_chunks_completed=project.discovery_chunks_completed,
        discovery_chunks_total=project.discovery_chunks_total,
        discovery_chunks_remaining=project.discovery_chunks_remaining,
        pipeline_stage=project.pipeline_stage,
        clip_retranscription_status=project.clip_retranscription_status,
        clip_retranscription_progress_pct=project.clip_retranscription_progress_pct,
        vocabulary_hints=project.vocabulary_hints,
        analysis_status=project.analysis_status,
        analysis_path=project.analysis_path,
        analysis_stage=project.analysis_stage,
        analysis_progress_pct=project.analysis_progress_pct,
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
