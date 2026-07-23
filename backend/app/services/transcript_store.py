from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.models.project import TranscriptDocument, TranscriptTier
from app.services.project_store import (
    get_transcript_output_dir,
    get_transcript_output_path,
    load_project,
    validate_project_id,
)
from app.services.transcription import TranscriptNotFoundError, TranscriptionProcessError


def get_discovery_transcript_path(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    return get_transcript_output_dir(validated_id) / settings.discovery_transcript_output_filename


def get_relative_discovery_transcript_path(project_id: str) -> str:
    validated_id = validate_project_id(project_id)
    return f"{validated_id}/{settings.discovery_transcript_output_filename}"


def get_discovery_chunks_dir(project_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    chunk_dir = get_transcript_output_dir(validated_id) / settings.discovery_chunks_subdir
    chunk_dir.mkdir(parents=True, exist_ok=True)
    return chunk_dir


def get_discovery_chunk_state_path(project_id: str) -> Path:
    return get_discovery_chunks_dir(project_id) / settings.discovery_chunk_state_filename


def get_discovery_chunk_transcript_path(project_id: str, chunk_index: int) -> Path:
    return get_discovery_chunks_dir(project_id) / f"chunk_{chunk_index:04d}.json"


def get_clip_quality_transcript_path(project_id: str, clip_id: str) -> Path:
    validated_id = validate_project_id(project_id)
    clip_dir = get_transcript_output_dir(validated_id) / settings.clip_transcripts_subdir
    clip_dir.mkdir(parents=True, exist_ok=True)
    return clip_dir / f"{clip_id}.json"


def _load_transcript_file(path: Path) -> TranscriptDocument:
    if not path.exists() or not path.is_file():
        raise TranscriptNotFoundError(
            "Transcript not found. Run transcription before loading the transcript."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TranscriptDocument.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise TranscriptionProcessError("Transcript file is corrupted.") from exc


def load_discovery_transcript(project_id: str) -> TranscriptDocument:
    load_project(project_id)
    return _load_transcript_file(get_discovery_transcript_path(project_id))


def load_workflow_transcript(project_id: str) -> TranscriptDocument:
    """Load the transcript used for analyze/select-clips/search workflows."""
    project = load_project(project_id)
    if project.discovery_transcript_path:
        discovery_path = settings.transcripts_dir / project.discovery_transcript_path
        if discovery_path.exists():
            return _load_transcript_file(discovery_path)
    discovery_path = get_discovery_transcript_path(project_id)
    if discovery_path.exists():
        return _load_transcript_file(discovery_path)
    return _load_transcript_file(get_transcript_output_path(project_id))


def load_full_quality_transcript(project_id: str) -> TranscriptDocument:
    load_project(project_id)
    document = _load_transcript_file(get_transcript_output_path(project_id))
    if document.transcript_tier in {TranscriptTier.DISCOVERY, TranscriptTier.LEGACY}:
        if document.transcript_tier == TranscriptTier.DISCOVERY:
            raise TranscriptNotFoundError(
                "Full-quality transcript not found. Run full-quality transcription first."
            )
    return document


def load_clip_quality_transcript(project_id: str, clip_id: str) -> TranscriptDocument | None:
    path = get_clip_quality_transcript_path(project_id, clip_id)
    if not path.exists():
        return None
    return _load_transcript_file(path)


def has_discovery_transcript(project_id: str) -> bool:
    project = load_project(project_id)
    if project.discovery_transcript_path:
        return (settings.transcripts_dir / project.discovery_transcript_path).exists()
    return get_discovery_transcript_path(project_id).exists()


def infer_discovery_language_hint(project_id: str, *, detected_language: str | None = None) -> str | None:
    """Best-effort language hint for discovery model selection (e.g. tiny.en)."""
    if detected_language:
        return detected_language

    if has_discovery_transcript(project_id):
        try:
            return load_discovery_transcript(project_id).language
        except (TranscriptionProcessError, TranscriptNotFoundError):
            pass

    transcript_path = get_transcript_output_path(project_id)
    if transcript_path.exists():
        try:
            return _load_transcript_file(transcript_path).language
        except TranscriptionProcessError:
            pass

    return None


def infer_transcript_tier(document: TranscriptDocument) -> TranscriptTier:
    if document.transcript_tier != TranscriptTier.LEGACY:
        return document.transcript_tier
    if document.quality_mode is None:
        return TranscriptTier.LEGACY
    return TranscriptTier.FULL_QUALITY
