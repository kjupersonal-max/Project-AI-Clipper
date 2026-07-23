from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.project import (
    CaptionSegment,
    CaptionWord,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptTier,
    TranscriptWord,
    TranscriptionQualityMode,
    TranscriptionQualityRating,
    utc_now_iso,
)
from app.services.audio_preprocessing import cleanup_temp_audio
from app.services.transcription_pipeline import run_multipass_transcription
from app.services.clip_boundary import (
    compute_padded_range,
    filter_segments_to_clip_range,
    remap_segments_to_clip_relative,
)
from app.services.project_store import get_audio_output_path, load_project, locate_video_file
from app.services.transcription import (
    TranscriptionProcessError,
    WhisperModelLoadError,
    _build_transcript_document,
    _sanitize_error_message,
)
from app.services.transcription_cache import build_cache_key, get_cached_transcript, store_cached_transcript
from app.services.transcription_config import (
    ResolvedTranscriptionSettings,
    resolve_transcription_settings,
    sanitize_vocabulary_hints,
)
from app.services.transcription_quality import analyze_transcription_quality
from app.services.video_processing import extract_audio_segment_to_wav, ensure_ffmpeg_tools

logger = logging.getLogger(__name__)


@dataclass
class ClipTranscriptionResult:
    segments: list[TranscriptSegment]
    language: str
    duration: float
    quality_rating: TranscriptionQualityRating
    warnings: list[str] = field(default_factory=list)
    quality_mode: TranscriptionQualityMode | None = None


def _temp_transcription_dir(project_id: str) -> Path:
    return settings.transcripts_dir / settings.transcription_temp_dir_name / project_id


def _extract_clip_audio(
    *,
    project_id: str,
    clip_start: float,
    clip_end: float,
    padding_seconds: float,
) -> tuple[Path, float, float, Path | None]:
    project = load_project(project_id)
    source_duration = project.video_metadata.duration_seconds if project.video_metadata else clip_end
    if source_duration is None:
        source_duration = clip_end
    padded = compute_padded_range(
        clip_start,
        clip_end,
        source_duration,
        padding_seconds=padding_seconds,
    )
    video_path = locate_video_file(project)
    temp_dir = _temp_transcription_dir(project_id)
    temp_dir.mkdir(parents=True, exist_ok=True)
    segment_path = temp_dir / f"clip_{clip_start:.3f}_{clip_end:.3f}.wav"
    ensure_ffmpeg_tools()
    extract_audio_segment_to_wav(
        video_path=video_path,
        output_path=segment_path,
        start_time=padded.padded_start,
        end_time=padded.padded_end,
    )
    return segment_path, padded.padded_start, padded.padded_end, temp_dir


def _run_transcription_on_audio(
    audio_path: Path,
    *,
    resolved: ResolvedTranscriptionSettings,
    project_id: str,
    clip_start: float | None = None,
    clip_end: float | None = None,
    use_cache: bool = True,
) -> tuple[list[TranscriptSegment], str, float, list[str]]:
    vocabulary = resolved.decode_options.get("initial_prompt")
    cache_key = build_cache_key(
        audio_path=audio_path,
        quality_mode=resolved.mode,
        model_size=resolved.model_size,
        language=resolved.decode_options.get("language"),
        vocabulary_hints=vocabulary,
        clip_start=clip_start,
        clip_end=clip_end,
        transcript_tier=TranscriptTier.CLIP_QUALITY,
    )
    if use_cache:
        cached = get_cached_transcript(cache_key)
        if cached is not None:
            return cached.segments, cached.language, cached.duration, [*resolved.warnings, "Used cached transcription result."]

    temp_dir = audio_path.parent / "multipass"
    warnings = list(resolved.warnings)
    try:
        multipass = run_multipass_transcription(
            resolved=resolved,
            source_audio_path=audio_path,
            temp_dir=temp_dir,
            project_id=project_id,
        )
        segments = multipass.segments
        warnings.extend(multipass.warnings)
        language = multipass.language
        duration = multipass.duration
        document = _build_transcript_document(
            project_id=project_id,
            language=language,
            duration=duration,
            segments=segments,
            transcript_tier=TranscriptTier.CLIP_QUALITY,
        )
        store_cached_transcript(cache_key, document)
        return segments, language, duration, warnings
    finally:
        cleanup_temp_audio(temp_dir)


def transcribe_clip_range(
    *,
    project_id: str,
    clip_start: float,
    clip_end: float,
    quality_mode: str | TranscriptionQualityMode | None = None,
    vocabulary_hints: str | None = None,
    padding_seconds: float | None = None,
) -> ClipTranscriptionResult:
    if clip_end <= clip_start:
        raise TranscriptionProcessError("Clip end time must be after start time.")

    padding = padding_seconds or settings.transcription_clip_boundary_padding_seconds
    hints = sanitize_vocabulary_hints(vocabulary_hints)
    project = load_project(project_id)
    resolved = resolve_transcription_settings(
        quality_mode=quality_mode,
        language=project.detected_language,
        vocabulary_hints=hints,
    )

    segment_path: Path | None = None
    temp_dir: Path | None = None
    try:
        segment_path, padded_start, padded_end, temp_dir = _extract_clip_audio(
            project_id=project_id,
            clip_start=clip_start,
            clip_end=clip_end,
            padding_seconds=padding,
        )
        absolute_segments, language, duration, warnings = _run_transcription_on_audio(
            segment_path,
            resolved=resolved,
            project_id=project_id,
            clip_start=clip_start,
            clip_end=clip_end,
        )
        offset_segments = [
            TranscriptSegment(
                id=segment.id,
                start=round(segment.start + padded_start, 3),
                end=round(segment.end + padded_start, 3),
                text=segment.text,
                words=[
                    TranscriptWord(
                        word=word.word,
                        start=round(word.start + padded_start, 3),
                        end=round(word.end + padded_start, 3),
                        probability=word.probability,
                    )
                    for word in segment.words
                ],
            )
            for segment in absolute_segments
        ]
        filtered = filter_segments_to_clip_range(offset_segments, clip_start, clip_end)
        relative = remap_segments_to_clip_relative(filtered, clip_start, clip_end)
        quality = analyze_transcription_quality(
            filtered,
            clip_start=clip_start,
            clip_end=clip_end,
            duration=clip_end - clip_start,
        )
        return ClipTranscriptionResult(
            segments=relative,
            language=language,
            duration=clip_end - clip_start,
            quality_rating=quality.rating,
            warnings=[*warnings, *quality.warnings],
            quality_mode=resolved.mode,
        )
    except WhisperModelLoadError:
        raise
    except Exception as exc:
        raise TranscriptionProcessError(
            _sanitize_error_message(f"Clip transcription failed: {exc}")
        ) from exc
    finally:
        if segment_path is not None:
            cleanup_temp_audio(segment_path)
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def transcript_segments_to_caption_segments(
    segments: list[TranscriptSegment],
    *,
    clip_duration: float,
) -> list[CaptionSegment]:
    captions: list[CaptionSegment] = []
    now = utc_now_iso()
    for index, segment in enumerate(segments):
        words = [
            CaptionWord(word=word.word, start=word.start, end=word.end)
            for word in segment.words
        ]
        if words:
            text = " ".join(word.word for word in words).strip()
            start = words[0].start
            end = words[-1].end
        else:
            text = segment.text.strip()
            start = segment.start
            end = segment.end
        if end <= start or start < 0 or end > clip_duration + 0.001:
            continue
        low_confidence = any(
            word.probability is not None and word.probability < 0.55 for word in segment.words
        )
        captions.append(
            CaptionSegment(
                id=f"cap-{index}-{int(start * 1000)}",
                text=text,
                start=start,
                end=end,
                words=words,
                sequence=index,
                created_at=now,
                updated_at=now,
                low_confidence=low_confidence,
            )
        )
    return captions
