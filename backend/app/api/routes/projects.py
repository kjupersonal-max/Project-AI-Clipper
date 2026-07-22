from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models.project import (
    AnalysisDocument,
    AnalyzeResponse,
    ExtractAudioResponse,
    InspectResponse,
    ProcessingStatus,
    ProjectResponse,
    TranscribeResponse,
    TranscriptDocument,
    project_to_response,
    utc_now_iso,
)
from app.services.project_store import (
    get_relative_analysis_path,
    get_relative_transcript_path,
    load_project,
    locate_video_file,
    save_project,
    validate_project_id,
)
from app.services.analysis.base import ProviderConfigurationError, AnalysisProviderError
from app.services.timeline_analysis import (
    AnalysisNotFoundError,
    AnalysisProcessError,
    AnalysisTranscriptRequiredError,
    InvalidTranscriptError,
    analyze_project_timeline,
    cleanup_analysis_output,
    load_project_analysis,
)
from app.services.transcription import (
    TranscriptionAudioNotFoundError,
    TranscriptionProcessError,
    TranscriptNotFoundError,
    WhisperModelLoadError,
    cleanup_transcript_output,
    load_project_transcript,
    transcribe_project_audio,
)
from app.services.video_processing import (
    FFprobeError,
    FFmpegProcessError,
    extract_project_audio,
    inspect_project_video,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


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


@router.post("/{project_id}/transcribe", response_model=TranscribeResponse)
def transcribe_project(project_id: str) -> TranscribeResponse:
    validate_project_id(project_id)
    project = load_project(project_id)

    started_at = utc_now_iso()
    project.transcription_status = ProcessingStatus.PROCESSING
    project.transcription_started_at = started_at
    project.transcription_completed_at = None
    project.transcript_path = None
    project.detected_language = None
    project.last_error = None
    project.append_log("Transcription started.")
    save_project(project)

    try:
        document = transcribe_project_audio(project_id)
        relative_path = get_relative_transcript_path(project_id)
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.COMPLETED
        project.transcript_path = relative_path
        project.detected_language = document.language
        project.transcription_completed_at = utc_now_iso()
        project.last_error = None
        project.append_log("Transcription completed.")
        save_project(project)

        return TranscribeResponse(
            project_id=project_id,
            status="completed",
            language=document.language,
            duration=document.duration,
            segment_count=document.segment_count,
            word_count=document.word_count,
            transcript_path=relative_path,
        )
    except HTTPException as exc:
        cleanup_transcript_output(project_id)
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        detail = exc.detail if isinstance(exc.detail, str) else "Transcription failed."
        project.last_error = detail
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {detail}", level="error")
        save_project(project)
        raise
    except TranscriptionAudioNotFoundError as exc:
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except WhisperModelLoadError as exc:
        cleanup_transcript_output(project_id)
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except TranscriptionProcessError as exc:
        cleanup_transcript_output(project_id)
        project = load_project(project_id)
        project.transcription_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.transcription_completed_at = utc_now_iso()
        project.append_log(f"Transcription failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc


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

    project.analysis_status = ProcessingStatus.PROCESSING
    project.analysis_started_at = utc_now_iso()
    project.analysis_completed_at = None
    project.analysis_path = None
    project.analysis_provider = None
    project.last_error = None
    project.append_log("Timeline analysis started.")
    save_project(project)

    try:
        document = analyze_project_timeline(project_id)
        relative_path = get_relative_analysis_path(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.COMPLETED
        project.analysis_path = relative_path
        project.analysis_provider = document.provider
        project.analysis_completed_at = utc_now_iso()
        project.last_error = None
        project.append_log("Timeline analysis completed.")
        save_project(project)

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
        cleanup_analysis_output(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.FAILED
        detail = exc.detail if isinstance(exc.detail, str) else "Timeline analysis failed."
        project.last_error = detail
        project.analysis_completed_at = utc_now_iso()
        project.append_log(f"Timeline analysis failed: {detail}", level="error")
        save_project(project)
        raise
    except AnalysisTranscriptRequiredError as exc:
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.analysis_completed_at = utc_now_iso()
        project.append_log(f"Timeline analysis failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except InvalidTranscriptError as exc:
        cleanup_analysis_output(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.analysis_completed_at = utc_now_iso()
        project.append_log(f"Timeline analysis failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ProviderConfigurationError as exc:
        cleanup_analysis_output(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.analysis_completed_at = utc_now_iso()
        project.append_log(f"Timeline analysis failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AnalysisProviderError as exc:
        cleanup_analysis_output(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.analysis_completed_at = utc_now_iso()
        project.append_log(f"Timeline analysis failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AnalysisProcessError as exc:
        cleanup_analysis_output(project_id)
        project = load_project(project_id)
        project.analysis_status = ProcessingStatus.FAILED
        project.last_error = exc.message
        project.analysis_completed_at = utc_now_iso()
        project.append_log(f"Timeline analysis failed: {exc.message}", level="error")
        save_project(project)
        raise HTTPException(status_code=422, detail=exc.message) from exc
