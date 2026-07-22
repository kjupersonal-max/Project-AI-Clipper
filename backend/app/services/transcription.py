from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.project import TranscriptDocument, TranscriptSegment, TranscriptWord
from app.services.project_store import (
    get_audio_output_path,
    get_relative_transcript_path,
    get_transcript_output_dir,
    get_transcript_output_path,
    load_project,
)

_whisper_model: Any | None = None
_whisper_model_error: str | None = None


class TranscriptionAudioNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class WhisperModelLoadError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TranscriptionProcessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TranscriptNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _sanitize_error_message(message: str, max_length: int = 240) -> str:
    cleaned = " ".join(message.strip().split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3] + "..."


def reset_whisper_model_cache() -> None:
    global _whisper_model, _whisper_model_error
    _whisper_model = None
    _whisper_model_error = None


def get_whisper_model() -> Any:
    global _whisper_model, _whisper_model_error

    if _whisper_model is not None:
        return _whisper_model

    if _whisper_model_error is not None:
        raise WhisperModelLoadError(_whisper_model_error)

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        _whisper_model_error = "faster-whisper is not installed."
        raise WhisperModelLoadError(_whisper_model_error) from exc

    try:
        _whisper_model = WhisperModel(
            settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    except Exception as exc:
        _whisper_model_error = _sanitize_error_message(
            f"Failed to load Whisper model '{settings.whisper_model_size}': {exc}"
        )
        raise WhisperModelLoadError(_whisper_model_error) from exc

    return _whisper_model


def locate_project_audio(project_id: str) -> Path:
    project = load_project(project_id)
    if not project.extracted_audio_path:
        raise TranscriptionAudioNotFoundError(
            "Extracted audio is not available. Run audio extraction first."
        )

    relative_parts = Path(project.extracted_audio_path).parts
    if not relative_parts or relative_parts[0] != project_id:
        raise TranscriptionAudioNotFoundError("Stored audio path is invalid.")

    audio_path = get_audio_output_path(project_id)
    if not audio_path.exists() or not audio_path.is_file():
        raise TranscriptionAudioNotFoundError("Extracted audio file not found.")

    if audio_path.stat().st_size == 0:
        raise TranscriptionAudioNotFoundError("Extracted audio file is empty.")

    return audio_path


def cleanup_transcript_output(project_id: str) -> None:
    transcript_dir = settings.transcripts_dir / project_id
    partial_path = transcript_dir / f"{settings.transcript_output_filename}.part"
    if partial_path.exists():
        partial_path.unlink(missing_ok=True)

    output_path = transcript_dir / settings.transcript_output_filename
    if output_path.exists():
        output_path.unlink(missing_ok=True)

    if transcript_dir.exists() and not any(transcript_dir.iterdir()):
        shutil.rmtree(transcript_dir, ignore_errors=True)


def _build_transcript_document(
    *,
    project_id: str,
    language: str,
    duration: float,
    segments: list[TranscriptSegment],
) -> TranscriptDocument:
    word_count = sum(len(segment.words) for segment in segments)
    return TranscriptDocument(
        project_id=project_id,
        language=language,
        duration=duration,
        segment_count=len(segments),
        word_count=word_count,
        segments=segments,
    )


def _serialize_transcript(document: TranscriptDocument) -> str:
    return json.dumps(document.model_dump(mode="json"), indent=2)


def _write_transcript_atomically(project_id: str, document: TranscriptDocument) -> str:
    output_dir = get_transcript_output_dir(project_id)
    output_path = get_transcript_output_path(project_id)
    partial_path = output_dir / f"{settings.transcript_output_filename}.part"

    partial_path.write_text(_serialize_transcript(document), encoding="utf-8")
    partial_path.replace(output_path)
    return get_relative_transcript_path(project_id)


def transcribe_project_audio(project_id: str) -> TranscriptDocument:
    audio_path = locate_project_audio(project_id)
    model = get_whisper_model()

    try:
        segments_iter, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
        )
    except Exception as exc:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError(
            _sanitize_error_message(f"Transcription failed: {exc}")
        ) from exc

    try:
        transcript_segments: list[TranscriptSegment] = []
        for segment in segments_iter:
            words = [
                TranscriptWord(
                    word=word.word.strip(),
                    start=round(word.start, 3),
                    end=round(word.end, 3),
                    probability=round(word.probability, 4)
                    if word.probability is not None
                    else None,
                )
                for word in (segment.words or [])
                if word.word.strip()
            ]
            transcript_segments.append(
                TranscriptSegment(
                    id=segment.id,
                    start=round(segment.start, 3),
                    end=round(segment.end, 3),
                    text=segment.text.strip(),
                    words=words,
                )
            )
    except Exception as exc:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError(
            _sanitize_error_message(f"Transcription failed while reading segments: {exc}")
        ) from exc

    if not transcript_segments:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError("Transcription produced no segments.")

    language = info.language or "unknown"
    duration = round(info.duration or 0.0, 3)
    document = _build_transcript_document(
        project_id=project_id,
        language=language,
        duration=duration,
        segments=transcript_segments,
    )

    try:
        _write_transcript_atomically(project_id, document)
    except Exception as exc:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError(
            _sanitize_error_message(f"Failed to save transcript: {exc}")
        ) from exc

    return document


def load_project_transcript(project_id: str) -> TranscriptDocument:
    load_project(project_id)

    transcript_path = get_transcript_output_path(project_id)
    if not transcript_path.exists() or not transcript_path.is_file():
        raise TranscriptNotFoundError(
            "Transcript not found. Run transcription before loading the transcript."
        )

    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
        return TranscriptDocument.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise TranscriptionProcessError("Transcript file is corrupted.") from exc
