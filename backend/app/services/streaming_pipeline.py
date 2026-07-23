from __future__ import annotations

import logging
import time
from typing import Callable

from app.core.config import settings
from app.models.project import PipelineStage, ProcessingStatus
from app.services.clip_retranscription import retranscribe_from_candidates_document
from app.services.clip_selection import select_project_clips
from app.services.discovery_transcription import run_discovery_transcription
from app.services.pipeline_timing import log_stage_event, log_timing_summary
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import analyze_project_timeline, analyze_transcript_segments_incrementally

logger = logging.getLogger(__name__)


def run_automated_vod_pipeline(
    project_id: str,
    *,
    vocabulary_hints: str | None = None,
    select_clips: bool = True,
    retranscribe_clips: bool = True,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict[str, object]:
    if not settings.automated_pipeline_enabled:
        raise RuntimeError("Automated VOD pipeline is disabled.")

    pipeline_started = time.perf_counter()
    log_stage_event("automated_vod_pipeline", "start", project_id=project_id)

    project = load_project(project_id)
    project.pipeline_stage = PipelineStage.DISCOVERY_TRANSCRIPTION.value
    save_project(project)

    incremental_analysis_enabled = True

    def _on_chunk_completed(chunk_index: int, _segments: list) -> None:
        if not incremental_analysis_enabled:
            return
        project_state = load_project(project_id)
        project_state.pipeline_stage = PipelineStage.CHUNK_ANALYSIS.value
        save_project(project_state)
        analyze_transcript_segments_incrementally(project_id, chunk_index=chunk_index)

    discovery_document = run_discovery_transcription(
        project_id,
        vocabulary_hints=vocabulary_hints,
        progress_callback=progress_callback,
        chunk_completed_callback=_on_chunk_completed,
    )

    project = load_project(project_id)
    project.pipeline_stage = PipelineStage.CHUNK_ANALYSIS.value
    save_project(project)

    analysis_document = analyze_project_timeline(
        project_id,
        progress_callback=progress_callback,
    )

    result: dict[str, object] = {
        "discovery_segment_count": discovery_document.segment_count,
        "analysis_segment_count": analysis_document.segment_count,
        "clip_candidate_count": analysis_document.clip_candidate_count,
    }

    if not select_clips:
        log_timing_summary(
            project_id=project_id,
            pipeline="automated_vod_pipeline",
            total_seconds=time.perf_counter() - pipeline_started,
            select_clips=False,
        )
        return result

    project = load_project(project_id)
    project.pipeline_stage = PipelineStage.CANDIDATE_GENERATION.value
    save_project(project)

    candidates_document = select_project_clips(project_id)
    result["selected_candidate_count"] = candidates_document.candidate_count

    project = load_project(project_id)
    project.pipeline_stage = PipelineStage.GLOBAL_RANKING.value
    save_project(project)

    if retranscribe_clips and candidates_document.candidates:
        retranscribe_from_candidates_document(project_id, candidates_document)
        result["retranscribed_clip_count"] = len(candidates_document.candidates)

    project = load_project(project_id)
    project.pipeline_stage = PipelineStage.FINAL_CAPTION_READY.value
    save_project(project)

    log_timing_summary(
        project_id=project_id,
        pipeline="automated_vod_pipeline",
        total_seconds=time.perf_counter() - pipeline_started,
        discovery_segments=discovery_document.segment_count,
        candidates=candidates_document.candidate_count,
    )
    return result
