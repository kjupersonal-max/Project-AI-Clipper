from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from app.core.config import settings
from app.models.project import (
    ClipCandidate,
    ClipCandidatesDocument,
    PipelineStage,
    ProcessingStatus,
    TranscriptDocument,
    TranscriptTier,
    TranscriptionQualityMode,
)
from app.services.clip_transcription import transcribe_clip_range, transcript_segments_to_caption_segments
from app.services.pipeline_timing import log_stage_event, log_timing_summary
from app.services.project_store import load_project, save_project
from app.services.transcript_store import get_clip_quality_transcript_path, load_clip_quality_transcript
from app.services.transcription import _build_transcript_document
from app.services.transcription_quality import analyze_transcription_quality

logger = logging.getLogger(__name__)


def _write_clip_quality_transcript(project_id: str, clip_id: str, document: TranscriptDocument) -> None:
    path = get_clip_quality_transcript_path(project_id, clip_id)
    temp_path = path.with_suffix(".part")
    temp_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")
    temp_path.replace(path)


def retranscribe_clip_range_for_captions(
    *,
    project_id: str,
    clip_id: str,
    clip_start: float,
    clip_end: float,
    candidate_id: str | None = None,
    quality_mode: str | TranscriptionQualityMode | None = None,
    padding_seconds: float | None = None,
) -> TranscriptDocument:
    started = time.perf_counter()
    padding = padding_seconds or settings.clip_retranscription_padding_seconds
    mode = quality_mode or settings.clip_retranscription_quality_mode
    log_stage_event(
        "clip_retranscription",
        "start",
        project_id=project_id,
        clip_id=clip_id,
        clip_start=f"{clip_start:.3f}",
        clip_end=f"{clip_end:.3f}",
        padding=f"{padding:.3f}",
        quality_mode=str(mode),
    )

    result = transcribe_clip_range(
        project_id=project_id,
        clip_start=clip_start,
        clip_end=clip_end,
        quality_mode=mode,
        padding_seconds=padding,
    )

    absolute_segments = [
        segment.model_copy(
            update={
                "start": round(segment.start + clip_start, 3),
                "end": round(segment.end + clip_start, 3),
                "words": [
                    word.model_copy(
                        update={
                            "start": round(word.start + clip_start, 3),
                            "end": round(word.end + clip_start, 3),
                        }
                    )
                    for word in segment.words
                ],
            }
        )
        for segment in result.segments
    ]

    quality = analyze_transcription_quality(
        absolute_segments,
        clip_start=clip_start,
        clip_end=clip_end,
        duration=clip_end - clip_start,
    )
    document = _build_transcript_document(
        project_id=project_id,
        language=result.language,
        duration=clip_end - clip_start,
        segments=absolute_segments,
        quality_mode=result.quality_mode,
        quality_rating=quality.rating,
        quality_warnings=[*result.warnings, *quality.warnings],
        transcript_tier=TranscriptTier.CLIP_QUALITY,
        clip_id=clip_id,
        candidate_id=candidate_id,
    )
    _write_clip_quality_transcript(project_id, clip_id, document)

    elapsed = time.perf_counter() - started
    log_timing_summary(
        project_id=project_id,
        pipeline="clip_retranscription",
        total_seconds=elapsed,
        clip_id=clip_id,
        quality_mode=str(result.quality_mode),
        segments=len(absolute_segments),
        audio_duration=f"{clip_end - clip_start:.3f}s",
        real_time_factor=f"{elapsed / max(clip_end - clip_start, 0.001):.3f}",
    )
    return document


def load_or_retranscribe_clip_quality_transcript(
    *,
    project_id: str,
    clip_id: str,
    clip_start: float,
    clip_end: float,
    candidate_id: str | None = None,
) -> TranscriptDocument:
    existing = load_clip_quality_transcript(project_id, clip_id)
    if existing is not None and existing.segments:
        return existing
    return retranscribe_clip_range_for_captions(
        project_id=project_id,
        clip_id=clip_id,
        clip_start=clip_start,
        clip_end=clip_end,
        candidate_id=candidate_id,
    )


def retranscribe_selected_clip_candidates(
    project_id: str,
    *,
    candidates: list[ClipCandidate],
    clip_ids: list[str] | None = None,
) -> list[TranscriptDocument]:
    project = load_project(project_id)
    project.clip_retranscription_status = ProcessingStatus.PROCESSING
    project.pipeline_stage = PipelineStage.CLIP_RETRANSCRIPTION.value
    project.clip_retranscription_progress_pct = 0.0
    save_project(project)

    documents: list[TranscriptDocument] = []
    total = len(candidates)
    for index, candidate in enumerate(candidates):
        clip_id = clip_ids[index] if clip_ids and index < len(clip_ids) else candidate.clip_id
        document = retranscribe_clip_range_for_captions(
            project_id=project_id,
            clip_id=clip_id,
            clip_start=candidate.start,
            clip_end=candidate.end,
            candidate_id=candidate.clip_id,
        )
        documents.append(document)
        project = load_project(project_id)
        project.clip_retranscription_progress_pct = round(((index + 1) / max(1, total)) * 100.0, 1)
        save_project(project)

    project = load_project(project_id)
    project.clip_retranscription_status = ProcessingStatus.COMPLETED
    project.pipeline_stage = PipelineStage.FINAL_CAPTION_READY.value
    project.clip_retranscription_progress_pct = 100.0
    save_project(project)
    return documents


def retranscribe_from_candidates_document(
    project_id: str,
    document: ClipCandidatesDocument,
) -> list[TranscriptDocument]:
    return retranscribe_selected_clip_candidates(project_id, candidates=document.candidates)
