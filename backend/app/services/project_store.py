from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings
from app.models.project import ProcessingStatus, ProjectMetadata

PROJECT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ProjectStoreError(Exception):
    pass


def validate_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.match(project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID format.")
    return project_id


def _resolve_within(base_dir: Path, target: Path) -> Path:
    base_resolved = base_dir.resolve()
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project path.") from exc
    return target_resolved


def get_project_dir(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    project_dir = _resolve_within(settings.upload_dir, settings.upload_dir / validated_id)
    return project_dir


def get_metadata_path(project_id: str) -> Path:
    return get_project_dir(project_id) / settings.project_metadata_filename


def ensure_backend_dirs() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    settings.analysis_dir.mkdir(parents=True, exist_ok=True)
    settings.clip_candidates_dir.mkdir(parents=True, exist_ok=True)


def create_project_metadata(
    *,
    project_id: str,
    original_filename: str,
    stored_video_path: str,
    size_bytes: int,
) -> ProjectMetadata:
    validate_project_id(project_id)
    project = ProjectMetadata(
        project_id=project_id,
        original_filename=original_filename,
        stored_video_path=stored_video_path,
        size_bytes=size_bytes,
        upload_status=ProcessingStatus.COMPLETED,
    )
    project.append_log("Video upload completed.")
    save_project(project)
    return project


def save_project(project: ProjectMetadata) -> None:
    ensure_backend_dirs()
    project_dir = get_project_dir(project.project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found.")

    metadata_path = project_dir / settings.project_metadata_filename
    project.touch()
    metadata_path.write_text(
        json.dumps(project.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def load_project(project_id: str) -> ProjectMetadata:
    validate_project_id(project_id)
    project_dir = settings.upload_dir / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found.")

    metadata_path = project_dir / settings.project_metadata_filename
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Project metadata not found.")

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return ProjectMetadata.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Project metadata is corrupted.",
        ) from exc


def locate_video_file(project: ProjectMetadata) -> Path:
    relative_parts = Path(project.stored_video_path).parts
    if not relative_parts or relative_parts[0] != project.project_id:
        raise HTTPException(status_code=500, detail="Stored video path is invalid.")

    video_path = _resolve_within(settings.upload_dir, settings.upload_dir.joinpath(*relative_parts))
    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Uploaded video file not found.")
    return video_path


def get_audio_output_dir(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    audio_dir = _resolve_within(settings.audio_dir, settings.audio_dir / validated_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def get_audio_output_path(project_id: str) -> Path:
    return get_audio_output_dir(project_id) / settings.audio_output_filename


def get_relative_audio_path(project_id: str) -> str:
    return f"{project_id}/{settings.audio_output_filename}"


def get_transcript_output_dir(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    transcript_dir = _resolve_within(
        settings.transcripts_dir,
        settings.transcripts_dir / validated_id,
    )
    transcript_dir.mkdir(parents=True, exist_ok=True)
    return transcript_dir


def get_transcript_output_path(project_id: str) -> Path:
    return get_transcript_output_dir(project_id) / settings.transcript_output_filename


def get_relative_transcript_path(project_id: str) -> str:
    return f"{project_id}/{settings.transcript_output_filename}"


def get_analysis_output_dir(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    analysis_dir = _resolve_within(
        settings.analysis_dir,
        settings.analysis_dir / validated_id,
    )
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir


def get_analysis_output_path(project_id: str) -> Path:
    return get_analysis_output_dir(project_id) / settings.analysis_output_filename


def get_relative_analysis_path(project_id: str) -> str:
    return f"{project_id}/{settings.analysis_output_filename}"


def get_clip_candidates_output_dir(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    clip_dir = _resolve_within(
        settings.clip_candidates_dir,
        settings.clip_candidates_dir / validated_id,
    )
    clip_dir.mkdir(parents=True, exist_ok=True)
    return clip_dir


def get_clip_candidates_output_path(project_id: str) -> Path:
    return get_clip_candidates_output_dir(project_id) / settings.clip_candidates_output_filename


def get_relative_clip_candidates_path(project_id: str) -> str:
    return f"{project_id}/{settings.clip_candidates_output_filename}"


def update_project(project_id: str, updater) -> ProjectMetadata:
    project = load_project(project_id)
    updater(project)
    save_project(project)
    return project
