from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.project import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptTier,
    TranscriptWord,
    TranscriptionQualityMode,
    TranscriptionQualityRating,
)
from app.services.audio_preprocessing import cleanup_temp_audio
from app.services.project_store import (
    get_audio_output_path,
    get_relative_transcript_path,
    get_transcript_output_dir,
    get_transcript_output_path,
    load_project,
    save_project,
)
from app.services.transcription_cache import build_cache_key, get_cached_transcript, store_cached_transcript
from app.services.transcription_config import (
    ResolvedTranscriptionSettings,
    mark_cuda_unavailable,
    resolve_transcription_settings,
    sanitize_vocabulary_hints,
    with_cpu_device,
)
from app.services.pipeline_timing import log_stage_event, log_timing_summary, log_transcription_trace
from app.services.transcription_pipeline import run_multipass_transcription
from app.services.transcription_progress import TranscriptionStage
from app.services.transcription_quality import analyze_transcription_quality

logger = logging.getLogger(__name__)

_whisper_models: dict[str, Any] = {}
_whisper_model_errors: dict[str, str] = {}


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
    global _whisper_models, _whisper_model_errors
    _whisper_models = {}
    _whisper_model_errors = {}
    from app.services.transcription_config import reset_cuda_availability_cache

    reset_cuda_availability_cache()


def _model_cache_key(resolved: ResolvedTranscriptionSettings) -> str:
    return f"{resolved.model_size}:{resolved.device}:{resolved.compute_type}"


def _is_cuda_runtime_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = (
        "cublas",
        "cudnn",
        "cudart",
        "cuda",
        "dll is not found",
        "cannot be loaded",
        "nvidia",
        "cudnn64",
    )
    return any(marker in message for marker in markers)


def _instantiate_whisper_model(
    model_size: str,
    *,
    device: str,
    compute_type: str,
) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
    )


def _load_whisper_model(resolved: ResolvedTranscriptionSettings) -> Any:
    cache_key = _model_cache_key(resolved)
    if cache_key in _whisper_models:
        logger.info(
            "model_load cache_hit=true model=%s device=%s compute_type=%s",
            resolved.model_size,
            resolved.device,
            resolved.compute_type,
        )
        return _whisper_models[cache_key]
    if cache_key in _whisper_model_errors:
        raise WhisperModelLoadError(_whisper_model_errors[cache_key])

    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError as exc:
        message = "faster-whisper is not installed."
        _whisper_model_errors[cache_key] = message
        raise WhisperModelLoadError(message) from exc

    load_started = time.perf_counter()
    try:
        model = _instantiate_whisper_model(
            resolved.model_size,
            device=resolved.device,
            compute_type=resolved.compute_type,
        )
    except Exception as exc:
        if resolved.device != "cuda" or not _is_cuda_runtime_error(exc):
            message = _sanitize_error_message(
                f"Failed to load Whisper model '{resolved.model_size}': {exc}"
            )
            _whisper_model_errors[cache_key] = message
            raise WhisperModelLoadError(message) from exc

        mark_cuda_unavailable(str(exc))
        cpu_resolved = with_cpu_device(resolved)
        cpu_cache_key = _model_cache_key(cpu_resolved)
        if cpu_cache_key in _whisper_models:
            return _whisper_models[cpu_cache_key]

        try:
            model = _instantiate_whisper_model(
                cpu_resolved.model_size,
                device=cpu_resolved.device,
                compute_type=cpu_resolved.compute_type,
            )
        except Exception as cpu_exc:
            message = _sanitize_error_message(
                f"Failed to load Whisper model '{resolved.model_size}' on CPU: {cpu_exc}"
            )
            _whisper_model_errors[cpu_cache_key] = message
            raise WhisperModelLoadError(message) from cpu_exc

        _whisper_models[cpu_cache_key] = model
        logger.info(
            "model_load cache_hit=false model=%s device=%s compute_type=%s elapsed=%.3fs fallback=cpu",
            cpu_resolved.model_size,
            cpu_resolved.device,
            cpu_resolved.compute_type,
            time.perf_counter() - load_started,
        )
        return model

    _whisper_models[cache_key] = model
    logger.info(
        "model_load cache_hit=false model=%s device=%s compute_type=%s elapsed=%.3fs",
        resolved.model_size,
        resolved.device,
        resolved.compute_type,
        time.perf_counter() - load_started,
    )
    return model


def get_whisper_model_for_settings(resolved: ResolvedTranscriptionSettings) -> Any:
    return _load_whisper_model(resolved)


def run_whisper_transcribe(
    resolved: ResolvedTranscriptionSettings,
    audio_path: str | Path,
    *,
    model: Any | None = None,
    **options: Any,
) -> tuple[Any, Any, ResolvedTranscriptionSettings]:
    """Load the model and transcribe, falling back to CPU if CUDA fails at runtime."""
    active_model = model or _load_whisper_model(resolved)
    try:
        segments_iter, info = active_model.transcribe(str(audio_path), **options)
        return segments_iter, info, resolved
    except Exception as exc:
        if resolved.device != "cuda" or not _is_cuda_runtime_error(exc):
            raise

        mark_cuda_unavailable(str(exc))
        cpu_resolved = with_cpu_device(resolved)
        cpu_model = _load_whisper_model(cpu_resolved)
        segments_iter, info = cpu_model.transcribe(str(audio_path), **options)
        return segments_iter, info, cpu_resolved


def transcribe_audio_to_segments(
    resolved: ResolvedTranscriptionSettings,
    audio_path: str | Path,
    *,
    model: Any | None = None,
    **options: Any,
) -> tuple[list[TranscriptSegment], Any, ResolvedTranscriptionSettings, Any]:
    """Transcribe audio and materialize segments with CPU fallback during iteration."""
    active_resolved = resolved
    active_model = model or _load_whisper_model(resolved)
    segments_iter, info, active_resolved = run_whisper_transcribe(
        active_resolved,
        audio_path,
        model=active_model,
        **options,
    )
    try:
        return iter_whisper_segments(segments_iter), info, active_resolved, active_model
    except Exception as exc:
        if active_resolved.device != "cuda" or not _is_cuda_runtime_error(exc):
            raise

        mark_cuda_unavailable(str(exc))
        cpu_resolved = with_cpu_device(active_resolved)
        cpu_model = _load_whisper_model(cpu_resolved)
        return transcribe_audio_to_segments(
            cpu_resolved,
            audio_path,
            model=cpu_model,
            **options,
        )


def get_whisper_model() -> Any:
    resolved = resolve_transcription_settings()
    return get_whisper_model_for_settings(resolved)


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


def iter_whisper_segments(segments_iter: Any) -> list[TranscriptSegment]:
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
    return transcript_segments


def _build_transcript_document(
    *,
    project_id: str,
    language: str,
    duration: float,
    segments: list[TranscriptSegment],
    quality_mode: TranscriptionQualityMode | None = None,
    quality_rating: TranscriptionQualityRating | None = None,
    quality_warnings: list[str] | None = None,
    vocabulary_hints: str | None = None,
    transcription_revision: int = 1,
    transcript_tier: TranscriptTier = TranscriptTier.LEGACY,
    chunk_index: int | None = None,
    chunk_start: float | None = None,
    chunk_end: float | None = None,
    clip_id: str | None = None,
    candidate_id: str | None = None,
) -> TranscriptDocument:
    word_count = sum(len(segment.words) for segment in segments)
    return TranscriptDocument(
        project_id=project_id,
        language=language,
        duration=duration,
        segment_count=len(segments),
        word_count=word_count,
        segments=segments,
        quality_mode=quality_mode,
        quality_rating=quality_rating,
        quality_warnings=quality_warnings or [],
        vocabulary_hints=vocabulary_hints,
        transcription_revision=transcription_revision,
        transcript_tier=transcript_tier,
        chunk_index=chunk_index,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        clip_id=clip_id,
        candidate_id=candidate_id,
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


def transcribe_project_audio(
    project_id: str,
    *,
    quality_mode: str | TranscriptionQualityMode | None = None,
    vocabulary_hints: str | None = None,
    use_cache: bool = True,
    use_full_quality: bool = False,
    language: str | None = None,
) -> TranscriptDocument:
    if not use_full_quality:
        from app.services.discovery_transcription import run_discovery_transcription
        from app.services.transcription_config import resolve_discovery_settings

        discovery_settings = resolve_discovery_settings(language=language)
        log_transcription_trace(
            event="path_selected",
            project_id=project_id,
            transcription_tier="discovery",
            transcription_path="discovery",
            model_name=discovery_settings.model_size,
            use_full_quality=False,
            language_hint=language,
        )
        return run_discovery_transcription(
            project_id,
            vocabulary_hints=vocabulary_hints,
            language=language,
            use_cache=use_cache,
        )

    pipeline_started = time.perf_counter()
    log_transcription_trace(
        event="path_selected",
        project_id=project_id,
        transcription_tier="full_quality",
        transcription_path="balanced",
        use_full_quality=True,
        quality_mode=str(quality_mode or "default"),
    )
    log_stage_event("transcription", "start", project_id=project_id, quality_mode=str(quality_mode or "default"))

    audio_path = locate_project_audio(project_id)
    project = load_project(project_id)
    hints = sanitize_vocabulary_hints(vocabulary_hints or project.vocabulary_hints)
    resolved = resolve_transcription_settings(
        quality_mode=quality_mode or project.transcription_quality_mode,
        language=project.detected_language,
        vocabulary_hints=hints,
    )

    cache_key = build_cache_key(
        audio_path=audio_path,
        quality_mode=resolved.mode,
        model_size=resolved.model_size,
        language=resolved.decode_options.get("language"),
        vocabulary_hints=hints,
        transcript_tier=TranscriptTier.FULL_QUALITY,
    )
    if use_cache:
        cached = get_cached_transcript(cache_key)
        if cached is not None:
            elapsed = time.perf_counter() - pipeline_started
            logger.info(
                "project=%s transcription cache_hit=true elapsed=%.3fs segments=%s",
                project_id,
                elapsed,
                cached.segment_count,
            )
            _write_transcript_atomically(project_id, cached)
            return cached

    temp_dir = settings.transcripts_dir / settings.transcription_temp_dir_name / project_id
    warnings = list(resolved.warnings)

    def _report_progress(stage: str, progress_pct: float, detail: str = "") -> None:
        project_state = load_project(project_id)
        project_state.transcription_stage = stage
        project_state.transcription_progress_pct = round(progress_pct, 1)
        if detail:
            project_state.append_log(f"Transcription {stage}: {detail}")
        else:
            project_state.append_log(f"Transcription stage: {stage}")
        save_project(project_state)

    try:
        multipass = run_multipass_transcription(
            resolved=resolved,
            source_audio_path=audio_path,
            temp_dir=temp_dir,
            language=project.detected_language,
            progress=_report_progress,
            project_id=project_id,
        )
        transcript_segments = multipass.segments
        warnings.extend(multipass.warnings)
        resolved = multipass.resolved
    except WhisperModelLoadError:
        cleanup_transcript_output(project_id)
        raise
    except Exception as exc:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError(
            _sanitize_error_message(f"Transcription failed: {exc}")
        ) from exc
    finally:
        cleanup_temp_audio(temp_dir)

    if not transcript_segments:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError("Transcription produced no segments.")

    language = multipass.language or "unknown"
    duration = round(multipass.duration or 0.0, 3)
    quality = analyze_transcription_quality(transcript_segments, duration=duration)
    document = _build_transcript_document(
        project_id=project_id,
        language=language,
        duration=duration,
        segments=transcript_segments,
        quality_mode=resolved.mode,
        quality_rating=quality.rating,
        quality_warnings=[*warnings, *quality.warnings],
        vocabulary_hints=hints,
        transcript_tier=TranscriptTier.FULL_QUALITY,
    )

    try:
        _write_transcript_atomically(project_id, document)
        store_cached_transcript(cache_key, document)
        project = load_project(project_id)
        project.transcription_stage = TranscriptionStage.COMPLETED.value
        project.transcription_progress_pct = 100.0
        project.active_transcript_tier = TranscriptTier.FULL_QUALITY
        project.transcript_path = get_relative_transcript_path(project_id)
        save_project(project)
    except Exception as exc:
        cleanup_transcript_output(project_id)
        raise TranscriptionProcessError(
            _sanitize_error_message(f"Failed to save transcript: {exc}")
        ) from exc

    total_elapsed = time.perf_counter() - pipeline_started
    timings = multipass.timings if multipass else {}
    log_transcription_trace(
        event="completed",
        project_id=project_id,
        transcription_tier="full_quality",
        transcription_path="balanced",
        model_name=resolved.model_size,
        use_full_quality=True,
        quality_mode=resolved.mode.value,
        model_load_seconds=timings.get("model_load"),
        transcription_seconds=timings.get("primary_transcription"),
        persistence_seconds=timings.get("transcript_persist"),
        total_wall_seconds=total_elapsed,
    )
    log_timing_summary(
        project_id=project_id,
        pipeline="transcription",
        total_seconds=total_elapsed,
        cache_hit=False,
        skipped=",".join(multipass.skipped_passes) if multipass.skipped_passes else "none",
        preprocessing=f"{timings.get('preprocessing', 0.0):.3f}s",
        primary_transcription=f"{timings.get('primary_transcription', 0.0):.3f}s",
        secondary_transcription=f"{timings.get('secondary_transcription', 0.0):.3f}s",
        recovery=f"{timings.get('recovery_total', 0.0):.3f}s",
        transcript_merge=f"{timings.get('transcript_merge', 0.0):.3f}s",
        multipass_total=f"{timings.get('total', 0.0):.3f}s",
        timings=timings,
    )

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
