import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models.project import (
    AnalysisDocument,
    AnalyzeResponse,
    ClipCandidatesDocument,
    ClipExportsListResponse,
    ClipCaptionsResponse,
    DeleteCaptionsResponse,
    DeleteClipResponse,
    ExportClipRequest,
    ExportClipResponse,
    FavoriteClipRequest,
    TrimClipRequest,
    ExtractAudioResponse,
    InspectResponse,
    ProcessingStatus,
    ProjectResponse,
    RenameClipRequest,
    SelectClipsRequest,
    SelectClipsResponse,
    TranscribeRequest,
    TranscriptTier,
    TranscribeResponse,
    TranscriptionDiagnosticsRequest,
    TranscriptDocument,
    UpdateCaptionsRequest,
    UpdateCaptionStyleRequest,
    RetranscribeRangeRequest,
    RetranscribeRangePreviewResponse,
    ApplyRetranscribeRangeRequest,
    InsertCaptionWordRequest,
    InsertCaptionSegmentRequest,
    SplitCaptionSegmentRequest,
    MergeCaptionSegmentsRequest,
    NudgeCaptionTimingRequest,
    DeleteCaptionWordRequest,
    UpdateVocabularyHintsRequest,
    TranscriptionQualityResponse,
    VisualAnalysisDocument,
    VisualAnalyzeResponse,
    VisualAnalysisStatus,
    project_to_response,
    utc_now_iso,
)
from app.core.config import settings
from app.services.audio_preprocessing import analyze_channel_levels
from app.services.pipeline_timing import log_stage_event, log_timing_summary, log_transcription_trace
from app.services.project_store import (
    get_relative_analysis_path,
    get_relative_clip_candidates_path,
    get_relative_transcript_path,
    load_project,
    locate_video_file,
    save_project,
    validate_project_id,
)
from app.services.analysis.base import ProviderConfigurationError, AnalysisProviderError
from app.services.analysis.diagnostics import get_analysis_provider_diagnostics
from app.services.clip_selection import (
    ClipCandidatesNotFoundError,
    ClipSelectionAnalysisRequiredError,
    ClipSelectionProcessError,
    ClipSelectionTranscriptRequiredError,
    InvalidAnalysisForSelectionError,
    cleanup_clip_candidates_output,
    invalidate_stale_clip_candidates,
    load_project_clip_candidates,
    select_project_clips,
)
from app.services.caption_render import (
    CaptionRenderInProgressError,
    CaptionRenderProcessError,
    CaptionRenderValidationError,
    format_caption_render_error_detail,
    render_project_clip_captions,
)
from app.services.clip_captions import (
    ClipCaptionsGenerationError,
    ClipCaptionsNotFoundError,
    ClipCaptionsValidationError,
    apply_retranscribe_range,
    generate_clip_captions,
    get_clip_captions,
    get_transcription_quality,
    manual_delete_word,
    manual_insert_segment,
    manual_insert_word,
    manual_merge_segments,
    manual_nudge_timing,
    manual_split_segment,
    preview_retranscribe_range,
    reset_clip_captions,
    reset_clip_caption_style,
    update_clip_captions,
    update_clip_caption_style,
    update_vocabulary_hints,
)
from app.services.clip_export import (
    ClipExportNotFoundError,
    ClipExportProcessError,
    ClipExportValidationError,
    delete_project_clip,
    export_project_clip,
    favorite_project_clip,
    list_project_clip_exports,
    locate_exported_clip,
    rename_project_clip,
    trim_project_clip,
)
from app.services.timeline_analysis import (
    AnalysisNotFoundError,
    AnalysisProcessError,
    AnalysisTranscriptRequiredError,
    InvalidTranscriptError,
    analyze_project_timeline,
    cleanup_analysis_output,
    cleanup_partial_analysis_output,
    has_existing_analysis_output,
    load_project_analysis,
)
from app.services.visual_analysis import (
    VisualAnalysisNotFoundError,
    VisualAnalysisProcessError,
    VisualAnalysisUnavailableError,
    analyze_project_visuals,
    load_project_visual_analysis,
    mark_visual_analysis_unavailable,
    visual_analysis_available,
)
from app.services.transcription import (
    TranscriptionAudioNotFoundError,
    TranscriptionProcessError,
    TranscriptNotFoundError,
    WhisperModelLoadError,
    cleanup_transcript_output,
    load_project_transcript,
    locate_project_audio,
    transcribe_project_audio,
)
from app.services.streaming_pipeline import run_automated_vod_pipeline
from app.services.transcript_store import (
    get_relative_discovery_transcript_path,
    infer_discovery_language_hint,
)
from app.services.video_processing import (
    FFprobeError,
    FFmpegProcessError,
    extract_project_audio,
    inspect_project_video,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = logging.getLogger(__name__)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str) -> ProjectResponse:
    validate_project_id(project_id)
    project = load_project(project_id)
    return project_to_response(project)


@router.get("/{project_id}/media/video")
def get_project_video(project_id: str) -> FileResponse:
    validate_project_id(project_id)
    project = load_project(project_id)
    video_path = locate_video_file(project)

    media_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    media_type = media_types.get(video_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=video_path,
        media_type=media_type,
        filename=project.original_filename,
    )


@router.get("/{project_id}/media/clips/{clip_id}")
def get_project_clip(project_id: str, clip_id: str) -> FileResponse:
    validate_project_id(project_id)
    load_project(project_id)

    try:
        record, clip_path = locate_exported_clip(project_id, clip_id)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipExportProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc

    return FileResponse(
        path=clip_path,
        media_type="video/mp4",
        filename=record.filename,
    )


@router.post("/{project_id}/clips/export", response_model=ExportClipResponse)
def export_clip(project_id: str, request: ExportClipRequest) -> ExportClipResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    project.append_log(
        f"Clip export started ({request.start_time:.3f}s to {request.end_time:.3f}s)."
    )
    save_project(project)

    try:
        response = export_project_clip(
            project_id,
            start_time=request.start_time,
            end_time=request.end_time,
            clip_name=request.clip_name,
            candidate_id=request.candidate_id,
        )
        project = load_project(project_id)
        project.append_log(f"Clip export completed: {response.filename} ({response.clip_id}).")
        project.last_error = None
        save_project(project)
        return response
    except HTTPException as exc:
        project = load_project(project_id)
        detail = exc.detail if isinstance(exc.detail, str) else "Clip export failed."
        project.last_error = detail
        project.append_log(f"Clip export failed: {detail}", level="error")
        save_project(project)
        raise
    except ClipExportValidationError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Clip export failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ClipExportProcessError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Clip export failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get("/{project_id}/clips/exports", response_model=ClipExportsListResponse)
def get_project_clip_exports(project_id: str) -> ClipExportsListResponse:
    validate_project_id(project_id)
    load_project(project_id)

    exports = list_project_clip_exports(project_id)
    return ClipExportsListResponse(project_id=project_id, exports=exports)


@router.patch(
    "/{project_id}/clips/{clip_id}",
    response_model=ExportClipResponse,
)
def rename_project_exported_clip(
    project_id: str,
    clip_id: str,
    request: RenameClipRequest,
) -> ExportClipResponse:
    validate_project_id(project_id)

    try:
        return rename_project_clip(project_id, clip_id, clip_name=request.clip_name)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipExportValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ClipExportProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/trim",
    response_model=ExportClipResponse,
)
def trim_project_exported_clip(
    project_id: str,
    clip_id: str,
    request: TrimClipRequest,
) -> ExportClipResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    project.append_log(
        f"Clip trim started from {clip_id} ({request.start_time:.3f}s to {request.end_time:.3f}s)."
    )
    save_project(project)

    try:
        response = trim_project_clip(
            project_id,
            clip_id,
            start_time=request.start_time,
            end_time=request.end_time,
            clip_name=request.clip_name,
        )
        project = load_project(project_id)
        project.append_log(f"Clip trim completed: {response.filename} ({response.clip_id}).")
        project.last_error = None
        save_project(project)
        return response
    except HTTPException as exc:
        project = load_project(project_id)
        detail = exc.detail if isinstance(exc.detail, str) else "Clip trim failed."
        project.last_error = detail
        project.append_log(f"Clip trim failed: {detail}", level="error")
        save_project(project)
        raise
    except ClipExportNotFoundError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Clip trim failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipExportValidationError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Clip trim failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ClipExportProcessError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Clip trim failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.patch(
    "/{project_id}/clips/{clip_id}/favorite",
    response_model=ExportClipResponse,
)
def favorite_project_exported_clip(
    project_id: str,
    clip_id: str,
    request: FavoriteClipRequest,
) -> ExportClipResponse:
    validate_project_id(project_id)

    try:
        return favorite_project_clip(project_id, clip_id, is_favorite=request.is_favorite)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipExportProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.delete(
    "/{project_id}/clips/{clip_id}",
    response_model=DeleteClipResponse,
)
def delete_project_exported_clip(project_id: str, clip_id: str) -> DeleteClipResponse:
    validate_project_id(project_id)

    try:
        delete_project_clip(project_id, clip_id)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipExportProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc

    return DeleteClipResponse(
        project_id=project_id,
        clip_id=clip_id,
        message="Exported clip deleted successfully.",
    )


@router.post(
    "/{project_id}/clips/{clip_id}/captions/generate",
    response_model=ClipCaptionsResponse,
)
def generate_project_clip_captions(project_id: str, clip_id: str) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    project.append_log(f"Caption generation started for clip {clip_id}.")
    save_project(project)

    try:
        response = generate_clip_captions(project_id, clip_id)
        project = load_project(project_id)
        project.append_log(
            f"Caption generation completed for clip {clip_id} ({len(response.segments)} segments)."
        )
        project.last_error = None
        save_project(project)
        return response
    except ClipExportNotFoundError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Caption generation failed at clip_lookup: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsGenerationError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Caption generation failed at caption_build: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Caption generation failed at caption_validation: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except TranscriptionProcessError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(
            f"Caption generation failed at clip_retranscription: {exc.message}",
            level="error",
        )
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get(
    "/{project_id}/clips/{clip_id}/captions",
    response_model=ClipCaptionsResponse,
)
def get_project_clip_captions(project_id: str, clip_id: str) -> ClipCaptionsResponse:
    validate_project_id(project_id)

    try:
        return get_clip_captions(project_id, clip_id)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.put(
    "/{project_id}/clips/{clip_id}/captions",
    response_model=ClipCaptionsResponse,
)
def update_project_clip_captions(
    project_id: str,
    clip_id: str,
    request: UpdateCaptionsRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)

    try:
        return update_clip_captions(project_id, clip_id, request.segments)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.delete(
    "/{project_id}/clips/{clip_id}/captions",
    response_model=DeleteCaptionsResponse,
)
def delete_project_clip_captions(project_id: str, clip_id: str) -> DeleteCaptionsResponse:
    validate_project_id(project_id)

    try:
        return reset_clip_captions(project_id, clip_id)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.put(
    "/{project_id}/clips/{clip_id}/captions/style",
    response_model=ClipCaptionsResponse,
)
def update_project_clip_caption_style(
    project_id: str,
    clip_id: str,
    request: UpdateCaptionStyleRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)

    try:
        return update_clip_caption_style(project_id, clip_id, request.style)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/style/reset",
    response_model=ClipCaptionsResponse,
)
def reset_project_clip_caption_style(
    project_id: str,
    clip_id: str,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)

    try:
        return reset_clip_caption_style(project_id, clip_id)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get(
    "/{project_id}/clips/{clip_id}/captions/transcription-quality",
    response_model=TranscriptionQualityResponse,
)
def get_project_clip_transcription_quality(
    project_id: str,
    clip_id: str,
) -> TranscriptionQualityResponse:
    validate_project_id(project_id)
    try:
        return get_transcription_quality(project_id, clip_id)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.put(
    "/{project_id}/clips/{clip_id}/captions/vocabulary-hints",
    response_model=ClipCaptionsResponse,
)
def update_project_clip_vocabulary_hints(
    project_id: str,
    clip_id: str,
    request: UpdateVocabularyHintsRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return update_vocabulary_hints(project_id, clip_id, request.vocabulary_hints)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/retranscribe/preview",
    response_model=RetranscribeRangePreviewResponse,
)
def preview_project_clip_retranscribe_range(
    project_id: str,
    clip_id: str,
    request: RetranscribeRangeRequest,
) -> RetranscribeRangePreviewResponse:
    validate_project_id(project_id)
    try:
        return preview_retranscribe_range(
            project_id,
            clip_id,
            range_start=request.start_time,
            range_end=request.end_time,
            quality_mode=request.quality_mode.value if request.quality_mode else None,
            vocabulary_hints=request.vocabulary_hints,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except TranscriptionProcessError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except WhisperModelLoadError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/retranscribe/apply",
    response_model=ClipCaptionsResponse,
)
def apply_project_clip_retranscribe_range(
    project_id: str,
    clip_id: str,
    request: ApplyRetranscribeRangeRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return apply_retranscribe_range(project_id, clip_id, request)
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/words",
    response_model=ClipCaptionsResponse,
)
def insert_project_clip_caption_word(
    project_id: str,
    clip_id: str,
    request: InsertCaptionWordRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return manual_insert_word(
            project_id,
            clip_id,
            segment_id=request.segment_id,
            word=request.word,
            start=request.start,
            end=request.end,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/segments",
    response_model=ClipCaptionsResponse,
)
def insert_project_clip_caption_segment(
    project_id: str,
    clip_id: str,
    request: InsertCaptionSegmentRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return manual_insert_segment(
            project_id,
            clip_id,
            text=request.text,
            start=request.start,
            end=request.end,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/segments/split",
    response_model=ClipCaptionsResponse,
)
def split_project_clip_caption_segment(
    project_id: str,
    clip_id: str,
    request: SplitCaptionSegmentRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return manual_split_segment(
            project_id,
            clip_id,
            segment_id=request.segment_id,
            split_time=request.split_time,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/segments/merge",
    response_model=ClipCaptionsResponse,
)
def merge_project_clip_caption_segments(
    project_id: str,
    clip_id: str,
    request: MergeCaptionSegmentsRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return manual_merge_segments(
            project_id,
            clip_id,
            first_segment_id=request.first_segment_id,
            second_segment_id=request.second_segment_id,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/segments/nudge",
    response_model=ClipCaptionsResponse,
)
def nudge_project_clip_caption_timing(
    project_id: str,
    clip_id: str,
    request: NudgeCaptionTimingRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return manual_nudge_timing(
            project_id,
            clip_id,
            segment_id=request.segment_id,
            delta_seconds=request.delta_seconds,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/words/delete",
    response_model=ClipCaptionsResponse,
)
def delete_project_clip_caption_word(
    project_id: str,
    clip_id: str,
    request: DeleteCaptionWordRequest,
) -> ClipCaptionsResponse:
    validate_project_id(project_id)
    try:
        return manual_delete_word(
            project_id,
            clip_id,
            segment_id=request.segment_id,
            word_index=request.word_index,
        )
    except ClipExportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipCaptionsValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/{project_id}/clips/{clip_id}/captions/render",
    response_model=ExportClipResponse,
)
def render_project_clip_captioned_export(
    project_id: str,
    clip_id: str,
) -> ExportClipResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    project.append_log(f"Caption render started for clip {clip_id}.")
    save_project(project)

    try:
        response = render_project_clip_captions(project_id, clip_id)
        project = load_project(project_id)
        project.append_log(
            f"Caption render completed for clip {clip_id} -> {response.clip_id} ({response.filename})."
        )
        project.last_error = None
        save_project(project)
        return response
    except ClipExportNotFoundError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Caption render failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except CaptionRenderValidationError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        project.append_log(f"Caption render failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except CaptionRenderInProgressError as exc:
        project = load_project(project_id)
        project.last_error = exc.message
        save_project(project)
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except CaptionRenderProcessError as exc:
        project = load_project(project_id)
        detail = format_caption_render_error_detail(exc)
        project.last_error = detail
        project.append_log(f"Caption render failed: {detail}", level="error")
        save_project(project)
        raise HTTPException(status_code=500, detail=detail) from exc


@router.post("/{project_id}/inspect", response_model=InspectResponse)
def inspect_project(project_id: str) -> InspectResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    project.inspection_status = ProcessingStatus.PROCESSING
    project.last_error = None
    project.append_log("Video inspection started.")
    save_project(project)

    try:
        metadata = inspect_project_video(project_id)
        project = load_project(project_id)
        project.inspection_status = ProcessingStatus.COMPLETED
        project.video_metadata = metadata
        project.last_error = None
        project.append_log("Video inspection completed.")
        save_project(project)

        return InspectResponse(
            project_id=project_id,
            inspection_status=ProcessingStatus.COMPLETED,
            video_metadata=metadata,
            message="Video inspection completed.",
        )
    except HTTPException as exc:
        project = load_project(project_id)
        project.inspection_status = ProcessingStatus.FAILED
        detail = exc.detail if isinstance(exc.detail, str) else "Video inspection failed."
        project.last_error = detail
        project.append_log(f"Video inspection failed: {detail}", level="error")
        save_project(project)
        raise
    except FFprobeError as exc:
        project = load_project(project_id)
        project.inspection_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.append_log(f"Video inspection failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post("/{project_id}/extract-audio", response_model=ExtractAudioResponse)
def extract_audio(project_id: str) -> ExtractAudioResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    project.audio_extraction_status = ProcessingStatus.PROCESSING
    project.last_error = None
    project.append_log("Audio extraction started.")
    save_project(project)

    try:
        relative_path, duration = extract_project_audio(project_id)
        project = load_project(project_id)
        project.audio_extraction_status = ProcessingStatus.COMPLETED
        project.extracted_audio_path = relative_path
        project.extracted_audio_duration_seconds = duration
        project.last_error = None
        project.append_log("Audio extraction completed.")
        save_project(project)

        return ExtractAudioResponse(
            project_id=project_id,
            audio_extraction_status=ProcessingStatus.COMPLETED,
            extracted_audio_path=relative_path,
            duration_seconds=duration,
            status="completed",
            message="Audio extracted successfully.",
        )
    except HTTPException as exc:
        project = load_project(project_id)
        project.audio_extraction_status = ProcessingStatus.FAILED
        detail = exc.detail if isinstance(exc.detail, str) else "Audio extraction failed."
        project.last_error = detail
        project.append_log(f"Audio extraction failed: {detail}", level="error")
        save_project(project)
        raise
    except FFmpegProcessError as exc:
        from app.services.video_processing import cleanup_audio_output

        cleanup_audio_output(project_id)
        project = load_project(project_id)
        project.audio_extraction_status = ProcessingStatus.FAILED
        project.extracted_audio_path = None
        project.extracted_audio_duration_seconds = None
        project.last_error = exc.message
        project.append_log(f"Audio extraction failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get("/{project_id}/transcript", response_model=TranscriptDocument)
def get_project_transcript(project_id: str) -> TranscriptDocument:
    validate_project_id(project_id)
    try:
        return load_project_transcript(project_id)
    except TranscriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except TranscriptionProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.post("/{project_id}/transcription/diagnostics")
def run_project_transcription_diagnostics(
    project_id: str,
    request: TranscriptionDiagnosticsRequest | None = None,
) -> dict[str, object]:
    """Development-only A/B transcription diagnostics for a project or clip range."""
    if not settings.enable_transcription_diagnostics:
        raise HTTPException(status_code=404, detail="Transcription diagnostics are disabled.")

    validate_project_id(project_id)
    body = request or TranscriptionDiagnosticsRequest()
    load_project(project_id)

    try:
        audio_path = locate_project_audio(project_id)
    except TranscriptionAudioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    temp_dir = (
        settings.transcripts_dir
        / settings.transcription_temp_dir_name
        / project_id
        / "_diag"
    )
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        channel_levels = [
            {
                "channel": item.channel,
                "peak_amplitude": item.peak_amplitude,
                "rms_level": item.rms_level,
            }
            for item in analyze_channel_levels(audio_path)
        ]
        variants = run_transcription_diagnostics_for_project(
            project_id=project_id,
            source_audio_path=audio_path,
            temp_dir=temp_dir,
            quality_mode=body.quality_mode.value if body.quality_mode else None,
            language=body.language,
            vocabulary_hints=body.vocabulary_hints,
            clip_start=body.clip_start,
            clip_end=body.clip_end,
        )
        return {
            "project_id": project_id,
            "clip_start": body.clip_start,
            "clip_end": body.clip_end,
            "channel_levels": channel_levels,
            "variants": variants,
        }
    except WhisperModelLoadError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except TranscriptionProcessError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post("/{project_id}/transcribe", response_model=TranscribeResponse)
def transcribe_project(
    project_id: str,
    request: TranscribeRequest | None = None,
) -> TranscribeResponse:
    validate_project_id(project_id)
    project = load_project(project_id)
    body = request or TranscribeRequest()
    language_hint = infer_discovery_language_hint(
        project_id,
        detected_language=project.detected_language,
    )
    transcription_path = "balanced" if body.use_full_quality else "discovery"

    log_transcription_trace(
        event="api_request_start",
        endpoint=f"POST /api/projects/{project_id}/transcribe",
        project_id=project_id,
        transcription_tier="full_quality" if body.use_full_quality else "discovery",
        transcription_path=transcription_path,
        use_full_quality=body.use_full_quality,
        quality_mode=body.quality_mode.value if body.quality_mode else None,
        language_hint=language_hint,
    )

    started_at = utc_now_iso()
    project.transcription_status = ProcessingStatus.PROCESSING
    project.transcription_started_at = started_at
    project.transcription_completed_at = None
    project.transcript_path = None
    project.detected_language = None
    project.last_error = None
    if body.quality_mode:
        project.transcription_quality_mode = body.quality_mode.value
    if body.vocabulary_hints is not None:
        project.vocabulary_hints = body.vocabulary_hints
    project.append_log("Transcription started.")
    save_project(project)

    endpoint_started = time.perf_counter()
    log_stage_event("api_transcribe", "start", project_id=project_id)

    try:
        document = transcribe_project_audio(
            project_id,
            quality_mode=body.quality_mode.value if body.quality_mode else None,
            vocabulary_hints=body.vocabulary_hints,
            use_full_quality=body.use_full_quality,
            language=language_hint,
        )
        relative_path = (
            get_relative_discovery_transcript_path(project_id)
            if document.transcript_tier == TranscriptTier.DISCOVERY
            else get_relative_transcript_path(project_id)
        )
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.COMPLETED
        project.transcript_path = relative_path
        if document.transcript_tier == TranscriptTier.DISCOVERY:
            project.discovery_transcript_path = relative_path
            project.active_transcript_tier = TranscriptTier.DISCOVERY
        elif document.transcript_tier == TranscriptTier.FULL_QUALITY:
            project.active_transcript_tier = TranscriptTier.FULL_QUALITY
        project.detected_language = document.language
        project.transcription_completed_at = utc_now_iso()
        project.last_error = None
        project.append_log("Transcription completed.")
        save_project(project)

        from app.services.transcription_config import resolve_discovery_settings

        resolved_model = (
            resolve_discovery_settings(language=document.language).model_size
            if document.transcript_tier == TranscriptTier.DISCOVERY
            else None
        )
        log_transcription_trace(
            event="api_request_completed",
            endpoint=f"POST /api/projects/{project_id}/transcribe",
            project_id=project_id,
            transcription_tier=document.transcript_tier.value if document.transcript_tier else None,
            transcription_path=transcription_path,
            model_name=resolved_model,
            use_full_quality=body.use_full_quality,
            total_wall_seconds=time.perf_counter() - endpoint_started,
            segment_count=document.segment_count,
            detected_language=document.language,
        )
        log_timing_summary(
            project_id=project_id,
            pipeline="api_transcribe",
            total_seconds=time.perf_counter() - endpoint_started,
            status="completed",
            segment_count=document.segment_count,
            word_count=document.word_count,
        )

        return TranscribeResponse(
            project_id=project_id,
            status="completed",
            language=document.language,
            duration=document.duration,
            segment_count=document.segment_count,
            word_count=document.word_count,
            transcript_path=relative_path,
            transcript_tier=document.transcript_tier,
            quality_mode=document.quality_mode,
            quality_rating=document.quality_rating,
            warnings=document.quality_warnings,
        )
    except HTTPException as exc:
        cleanup_transcript_output(project_id)
        log_timing_summary(
            project_id=project_id,
            pipeline="api_transcribe",
            total_seconds=time.perf_counter() - endpoint_started,
            status="failed",
        )
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        detail = exc.detail if isinstance(exc.detail, str) else "Transcription failed."
        project.last_error = detail
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {detail}", level="error")
        save_project(project)
        raise
    except TranscriptionAudioNotFoundError as exc:
        log_timing_summary(
            project_id=project_id,
            pipeline="api_transcribe",
            total_seconds=time.perf_counter() - endpoint_started,
            status="failed",
        )
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except WhisperModelLoadError as exc:
        cleanup_transcript_output(project_id)
        log_timing_summary(
            project_id=project_id,
            pipeline="api_transcribe",
            total_seconds=time.perf_counter() - endpoint_started,
            status="failed",
        )
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except TranscriptionProcessError as exc:
        cleanup_transcript_output(project_id)
        log_timing_summary(
            project_id=project_id,
            pipeline="api_transcribe",
            total_seconds=time.perf_counter() - endpoint_started,
            status="failed",
        )
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    finally:
        project = load_project(project_id)
        if project.transcription_status == ProcessingStatus.PROCESSING:
            project.transcription_status = ProcessingStatus.FAILED
            project.transcription_completed_at = utc_now_iso()
            project.last_error = project.last_error or "Transcription did not complete."
            project.append_log("Transcription ended without completion.", level="error")
            save_project(project)


@router.post("/{project_id}/automated-pipeline")
def run_project_automated_pipeline(project_id: str) -> dict[str, object]:
    validate_project_id(project_id)
    project = load_project(project_id)
    project.append_log("Automated VOD pipeline started.")
    save_project(project)
    try:
        result = run_automated_vod_pipeline(project_id)
        project = load_project(project_id)
        project.append_log("Automated VOD pipeline completed.")
        save_project(project)
        return {"project_id": project_id, "status": "completed", **result}
    except Exception as exc:
        project = load_project(project_id)
        project.last_error = str(exc)
        project.append_log(f"Automated VOD pipeline failed: {exc}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analysis/provider-diagnostics")
def analysis_provider_diagnostics(dry_run: bool = False) -> dict[str, object]:
    return get_analysis_provider_diagnostics(dry_run=dry_run)


@router.get("/{project_id}/analysis", response_model=AnalysisDocument)
def get_project_analysis(project_id: str) -> AnalysisDocument:
    validate_project_id(project_id)
    try:
        return load_project_analysis(project_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except AnalysisProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.post("/{project_id}/analyze", response_model=AnalyzeResponse)
def analyze_project(project_id: str) -> AnalyzeResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    previous_analysis_path = project.analysis_path
    previous_analysis_provider = project.analysis_provider
    previous_analysis_completed_at = project.analysis_completed_at
    had_existing_analysis = has_existing_analysis_output(project_id)

    project.analysis_status = ProcessingStatus.PROCESSING
    project.analysis_started_at = utc_now_iso()
    project.last_error = None
    project.append_log("Timeline analysis started.")
    save_project(project)

    endpoint_started = time.perf_counter()
    log_stage_event("api_analyze", "start", project_id=project_id)

    def restore_previous_analysis_state(*, detail: str, level: str = "error") -> None:
        nonlocal project
        project = load_project(project_id)
        if had_existing_analysis and has_existing_analysis_output(project_id):
            project.analysis_status = ProcessingStatus.COMPLETED
            project.analysis_path = previous_analysis_path
            project.analysis_provider = previous_analysis_provider
            project.analysis_completed_at = previous_analysis_completed_at
            project.last_error = detail
            project.append_log(f"Timeline analysis failed; kept previous analysis: {detail}", level=level)
        else:
            project.analysis_status = ProcessingStatus.FAILED
            project.analysis_path = None
            project.analysis_provider = None
            project.analysis_completed_at = utc_now_iso()
            project.last_error = detail
            project.append_log(f"Timeline analysis failed: {detail}", level=level)
        save_project(project)

    def cleanup_failed_analysis_output() -> None:
        if had_existing_analysis:
            cleanup_partial_analysis_output(project_id)
        else:
            cleanup_analysis_output(project_id)

    try:
        document = analyze_project_timeline(project_id)
        relative_path = get_relative_analysis_path(project_id)
        cleanup_clip_candidates_output(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.COMPLETED
        project.analysis_stage = "completed"
        project.analysis_progress_pct = 100.0
        project.analysis_path = relative_path
        project.analysis_provider = document.provider
        project.analysis_completed_at = utc_now_iso()
        project.clip_selection_status = ProcessingStatus.PENDING
        project.clip_candidates_path = None
        project.clip_candidate_count = None
        project.last_error = None
        project.append_log("Timeline analysis completed.")
        save_project(project)

        log_timing_summary(
            project_id=project_id,
            pipeline="api_analyze",
            total_seconds=time.perf_counter() - endpoint_started,
            status="completed",
            segment_count=document.segment_count,
            clip_candidate_count=document.clip_candidate_count,
        )

        return AnalyzeResponse(
            project_id=project_id,
            status="completed",
            provider=document.provider,
            model=document.model,
            is_heuristic_fallback=document.is_heuristic_fallback,
            segment_count=document.segment_count,
            clip_candidate_count=document.clip_candidate_count,
            analysis_path=relative_path,
        )
    except HTTPException as exc:
        cleanup_failed_analysis_output()
        detail = exc.detail if isinstance(exc.detail, str) else "Timeline analysis failed."
        restore_previous_analysis_state(detail=detail)
        raise
    except AnalysisTranscriptRequiredError as exc:
        restore_previous_analysis_state(detail=exc.message)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except InvalidTranscriptError as exc:
        cleanup_failed_analysis_output()
        restore_previous_analysis_state(detail=exc.message)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ProviderConfigurationError as exc:
        cleanup_failed_analysis_output()
        restore_previous_analysis_state(detail=exc.message)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AnalysisProviderError as exc:
        cleanup_failed_analysis_output()
        restore_previous_analysis_state(detail=exc.message)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AnalysisProcessError as exc:
        cleanup_failed_analysis_output()
        restore_previous_analysis_state(detail=exc.message)
        project = load_project(project_id)
        project.analysis_stage = "failed"
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    finally:
        project = load_project(project_id)
        if project.analysis_status == ProcessingStatus.PROCESSING:
            project.analysis_status = ProcessingStatus.FAILED
            project.analysis_stage = "failed"
            project.analysis_completed_at = utc_now_iso()
            project.last_error = project.last_error or "Timeline analysis did not complete."
            project.append_log("Timeline analysis ended without completion.", level="error")
            save_project(project)


@router.get("/{project_id}/clip-candidates", response_model=ClipCandidatesDocument)
def get_project_clip_candidates(project_id: str) -> ClipCandidatesDocument:
    validate_project_id(project_id)
    invalidate_stale_clip_candidates(project_id)
    try:
        return load_project_clip_candidates(project_id)
    except ClipCandidatesNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipSelectionProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


@router.post("/{project_id}/select-clips", response_model=SelectClipsResponse)
def select_clips(
    project_id: str,
    request: SelectClipsRequest | None = None,
) -> SelectClipsResponse:
    validate_project_id(project_id)
    invalidate_stale_clip_candidates(project_id)
    project = load_project(project_id)
    options = request or SelectClipsRequest()

    project.clip_selection_status = ProcessingStatus.PROCESSING
    project.clip_selection_started_at = utc_now_iso()
    project.clip_selection_completed_at = None
    project.clip_candidates_path = None
    project.clip_candidate_count = None
    project.last_error = None
    project.append_log("Clip selection started.")
    save_project(project)

    endpoint_started = time.perf_counter()
    log_stage_event("api_select_clips", "start", project_id=project_id)

    try:
        document = select_project_clips(
            project_id,
            min_duration_seconds=options.min_duration_seconds,
            max_duration_seconds=options.max_duration_seconds,
            max_gap_seconds=options.max_gap_seconds,
            max_candidates=options.max_candidates,
            min_score=options.min_score,
        )
        relative_path = get_relative_clip_candidates_path(project_id)
        project = load_project(project_id)
        project.clip_selection_status = ProcessingStatus.COMPLETED
        project.clip_candidates_path = relative_path
        project.clip_selection_completed_at = utc_now_iso()
        project.clip_candidate_count = document.candidate_count
        project.last_error = None
        project.append_log(
            f"Clip selection completed with {document.candidate_count} proposed candidates."
        )
        save_project(project)

        log_timing_summary(
            project_id=project_id,
            pipeline="api_select_clips",
            total_seconds=time.perf_counter() - endpoint_started,
            status="completed",
            candidate_count=document.candidate_count,
        )

        return SelectClipsResponse(
            project_id=project_id,
            status="completed",
            candidate_count=document.candidate_count,
            clip_candidates_path=relative_path,
        )
    except HTTPException as exc:
        cleanup_clip_candidates_output(project_id)
        project = load_project(project_id)
        project.clip_selection_status = ProcessingStatus.FAILED
        detail = exc.detail if isinstance(exc.detail, str) else "Clip selection failed."
        project.last_error = detail
        project.clip_selection_completed_at = utc_now_iso()
        project.append_log(f"Clip selection failed: {detail}", level="error")
        save_project(project)
        raise
    except ClipSelectionTranscriptRequiredError as exc:
        project = load_project(project_id)
        project.clip_selection_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.clip_selection_completed_at = utc_now_iso()
        project.append_log(f"Clip selection failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ClipSelectionAnalysisRequiredError as exc:
        project = load_project(project_id)
        project.clip_selection_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.clip_selection_completed_at = utc_now_iso()
        project.append_log(f"Clip selection failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except InvalidAnalysisForSelectionError as exc:
        cleanup_clip_candidates_output(project_id)
        project = load_project(project_id)
        project.clip_selection_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.clip_selection_completed_at = utc_now_iso()
        project.append_log(f"Clip selection failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ClipSelectionProcessError as exc:
        cleanup_clip_candidates_output(project_id)
        project = load_project(project_id)
        project.clip_selection_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.clip_selection_completed_at = utc_now_iso()
        project.append_log(f"Clip selection failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    finally:
        project = load_project(project_id)
        if project.clip_selection_status == ProcessingStatus.PROCESSING:
            project.clip_selection_status = ProcessingStatus.FAILED
            project.clip_selection_completed_at = utc_now_iso()
            project.last_error = project.last_error or "Clip selection did not complete."
            project.append_log("Clip selection ended without completion.", level="error")
            save_project(project)


@router.post("/{project_id}/visual-analyze", response_model=VisualAnalyzeResponse)
def visual_analyze_project(project_id: str, force: bool = False) -> VisualAnalyzeResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    if not settings.visual_analysis_enabled:
        mark_visual_analysis_unavailable(
            project_id,
            reason="Visual analysis is disabled in configuration.",
        )
        raise HTTPException(
            status_code=503,
            detail="Visual analysis is disabled in configuration.",
        )

    if not visual_analysis_available():
        mark_visual_analysis_unavailable(
            project_id,
            reason="FFmpeg is unavailable for visual analysis.",
        )
        raise HTTPException(
            status_code=503,
            detail="Visual analysis is unavailable because FFmpeg is not installed.",
        )

    endpoint_started = time.perf_counter()
    log_stage_event("api_visual_analyze", "start", project_id=project_id, force=force)

    try:
        document = analyze_project_visuals(project_id, force=force)
        project = load_project(project_id)
        elapsed = time.perf_counter() - endpoint_started
        cached = elapsed < 0.05 and not force
        message = (
            "Visual analysis loaded from cache."
            if cached
            else "Visual analysis completed."
        )
        project.append_log(message)
        save_project(project)

        log_timing_summary(
            project_id=project_id,
            pipeline="api_visual_analyze",
            total_seconds=time.perf_counter() - endpoint_started,
            status="completed",
            sampled_frame_count=document.sampled_frame_count,
            window_count=len(document.windows),
        )

        return VisualAnalyzeResponse(
            project_id=project_id,
            status=VisualAnalysisStatus.COMPLETED,
            visual_analysis_path=project.visual_analysis_path,
            processing_duration_seconds=document.processing_duration_seconds,
            sampled_frame_count=document.sampled_frame_count,
            window_count=len(document.windows),
            warnings=document.warnings,
            message=message,
        )
    except VisualAnalysisUnavailableError as exc:
        mark_visual_analysis_unavailable(project_id, reason=exc.message)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except VisualAnalysisProcessError as exc:
        project = load_project(project_id)
        project.visual_analysis_status = VisualAnalysisStatus.FAILED
        project.visual_analysis_completed_at = utc_now_iso()
        project.last_error = exc.message
        project.append_log(f"Visual analysis failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    finally:
        project = load_project(project_id)
        if project.visual_analysis_status == VisualAnalysisStatus.PROCESSING:
            project.visual_analysis_status = VisualAnalysisStatus.FAILED
            project.visual_analysis_completed_at = utc_now_iso()
            project.last_error = project.last_error or "Visual analysis did not complete."
            project.append_log("Visual analysis ended without completion.", level="error")
            save_project(project)


@router.get("/{project_id}/visual-analysis", response_model=VisualAnalysisDocument)
def get_project_visual_analysis(project_id: str) -> VisualAnalysisDocument:
    validate_project_id(project_id)
    try:
        return load_project_visual_analysis(project_id)
    except VisualAnalysisNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except VisualAnalysisProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc
