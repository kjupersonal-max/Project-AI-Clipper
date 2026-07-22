from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models.project import (
    ExtractAudioResponse,
    InspectResponse,
    ProcessingStatus,
    ProjectResponse,
    project_to_response,
)
from app.services.project_store import (
    load_project,
    locate_video_file,
    save_project,
    validate_project_id,
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
