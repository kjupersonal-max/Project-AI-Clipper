from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable
from itertools import batched

from pydantic import ValidationError

from app.core.config import settings
from app.models.project import AnalysisDocument, SegmentAnalysis, TranscriptDocument, TranscriptSegment
from app.services.analysis.base import AnalysisProviderError, ProviderConfigurationError
from app.services.analysis.heuristic import HeuristicAnalysisProvider
from app.services.analysis_pipeline import AnalysisPipelineError, AnalysisTimeoutError, extract_local_features, run_hierarchical_analysis
from app.services.analysis_timing import AnalysisTimingCollector
from app.services.pipeline_timing import log_stage_event, log_timing_summary
from app.services.project_store import (
    get_analysis_output_dir,
    get_analysis_output_path,
    get_relative_analysis_path,
    load_project,
    save_project,
)
from app.services.transcription import (
    TranscriptNotFoundError,
    load_project_transcript,
)
from app.services.transcript_store import get_discovery_chunk_transcript_path, load_workflow_transcript

logger = logging.getLogger(__name__)


class AnalysisTranscriptRequiredError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidTranscriptError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AnalysisProcessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AnalysisNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _sanitize_error_message(message: str, max_length: int = 240) -> str:
    cleaned = " ".join(message.strip().split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3] + "..."


def cleanup_partial_analysis_output(project_id: str) -> None:
    analysis_dir = settings.analysis_dir / project_id
    partial_path = analysis_dir / f"{settings.analysis_output_filename}.part"
    if partial_path.exists():
        partial_path.unlink(missing_ok=True)


def cleanup_analysis_output(project_id: str) -> None:
    cleanup_partial_analysis_output(project_id)

    output_path = get_analysis_output_path(project_id)
    if output_path.exists():
        output_path.unlink(missing_ok=True)

    analysis_dir = settings.analysis_dir / project_id
    if analysis_dir.exists() and not any(analysis_dir.iterdir()):
        shutil.rmtree(analysis_dir, ignore_errors=True)


def has_existing_analysis_output(project_id: str) -> bool:
    return get_analysis_output_path(project_id).exists()


def _validate_segment_alignment(
    transcript_segments: list[TranscriptSegment],
    analyzed_segments: list[SegmentAnalysis],
) -> None:
    if len(transcript_segments) != len(analyzed_segments):
        raise AnalysisProcessError(
            "Analysis provider returned a different number of segments than the transcript."
        )

    for source, result in zip(transcript_segments, analyzed_segments, strict=True):
        if result.segment_id != source.id:
            raise AnalysisProcessError(
                f"Analysis segment_id mismatch for transcript segment {source.id}."
            )
        if result.text.strip() != source.text.strip():
            raise AnalysisProcessError(
                f"Analysis text mismatch for transcript segment {source.id}."
            )
        if result.start != source.start or result.end != source.end:
            raise AnalysisProcessError(
                f"Analysis timing mismatch for transcript segment {source.id}."
            )


def _validate_provider_output(results: list[SegmentAnalysis]) -> list[SegmentAnalysis]:
    validated: list[SegmentAnalysis] = []
    for result in results:
        try:
            validated.append(SegmentAnalysis.model_validate(result.model_dump(mode="json")))
        except ValidationError as exc:
            raise AnalysisProcessError(
                _sanitize_error_message(f"Invalid analysis output: {exc}")
            ) from exc
    return validated


def _write_analysis_atomically(project_id: str, document: AnalysisDocument) -> str:
    output_dir = get_analysis_output_dir(project_id)
    output_path = get_analysis_output_path(project_id)
    partial_path = output_dir / f"{settings.analysis_output_filename}.part"

    partial_path.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    partial_path.replace(output_path)
    return get_relative_analysis_path(project_id)


def _require_completed_transcript(project_id: str):
    project = load_project(project_id)
    if project.transcription_status.value != "completed":
        raise AnalysisTranscriptRequiredError(
            "Transcription must be completed before timeline analysis."
        )

    try:
        transcript = load_workflow_transcript(project_id)
    except TranscriptNotFoundError as exc:
        raise AnalysisTranscriptRequiredError(exc.message) from exc

    if not transcript.segments:
        raise InvalidTranscriptError("Transcript contains no segments to analyze.")

    return transcript


def _analysis_windows(
    segments: list[TranscriptSegment],
    *,
    window_seconds: float,
    overlap_seconds: float,
) -> list[list[TranscriptSegment]]:
    if not segments:
        return []
    duration = max(segment.end for segment in segments)
    if duration <= settings.analysis_long_video_threshold_seconds:
        return [segments]

    windows: list[list[TranscriptSegment]] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + window_seconds)
        window_segments = [
            segment
            for segment in segments
            if segment.end > start and segment.start < end
        ]
        if window_segments:
            windows.append(window_segments)
        if end >= duration:
            break
        start = max(0.0, end - overlap_seconds)
    return windows or [segments]


def _update_analysis_progress(
    project_id: str,
    *,
    stage: str,
    progress_pct: float,
    detail: str,
) -> None:
    project = load_project(project_id)
    project.analysis_stage = stage
    project.analysis_progress_pct = round(progress_pct, 1)
    project.append_log(f"Analysis {stage}: {detail}")
    save_project(project)


def analyze_project_timeline(
    project_id: str,
    *,
    progress_callback: Callable[[str, float, str], None] | None = None,
    timing_collector: AnalysisTimingCollector | None = None,
) -> AnalysisDocument:
    transcript = _require_completed_transcript(project_id)
    started = time.perf_counter()
    log_stage_event(
        "analysis",
        "start",
        project_id=project_id,
        segments=transcript.segment_count,
        duration=f"{transcript.duration:.3f}s",
    )

    preserve_existing = has_existing_analysis_output(project_id)
    timing = timing_collector or AnalysisTimingCollector(enabled=False)
    timing.start_stage("transcript_load")
    timing.end_stage("transcript_load", segments=transcript.segment_count)

    def _combined_progress(stage: str, percent: float, detail: str) -> None:
        _update_analysis_progress(project_id, stage=stage, progress_pct=percent, detail=detail)
        if progress_callback is not None:
            progress_callback(stage, percent, detail)

    def _cleanup_failure_output() -> None:
        if preserve_existing:
            cleanup_partial_analysis_output(project_id)
        else:
            cleanup_analysis_output(project_id)

    tier = transcript.transcript_tier.value if transcript.transcript_tier else "legacy"

    try:
        timing.start_stage("endpoint_entry")
        timing.end_stage("endpoint_entry")
        analyzed_segments, provider_name, model_name, is_heuristic = run_hierarchical_analysis(
            project_id=project_id,
            segments=transcript.segments,
            transcript_tier=tier,
            progress_callback=_combined_progress,
            timing_collector=timing,
        )
    except AnalysisTimeoutError as exc:
        _cleanup_failure_output()
        raise AnalysisProcessError(
            _sanitize_error_message(f"Timeline analysis timed out during {exc.stage}: {exc.message}")
        ) from exc
    except AnalysisPipelineError as exc:
        _cleanup_failure_output()
        raise AnalysisProcessError(_sanitize_error_message(exc.message)) from exc
    except AnalysisProviderError:
        _cleanup_failure_output()
        raise
    except Exception as exc:
        _cleanup_failure_output()
        raise AnalysisProcessError(
            _sanitize_error_message(f"Timeline analysis failed: {exc}")
        ) from exc

    if not analyzed_segments:
        _cleanup_failure_output()
        raise AnalysisProcessError("Timeline analysis produced no segment results.")

    timing.start_stage("response_serialization")
    clip_candidate_count = sum(1 for segment in analyzed_segments if segment.clip_candidate)
    document = AnalysisDocument(
        project_id=project_id,
        provider=provider_name,
        model=model_name,
        is_heuristic_fallback=is_heuristic,
        segment_count=len(analyzed_segments),
        clip_candidate_count=clip_candidate_count,
        segments=analyzed_segments,
    )
    timing.end_stage("response_serialization", segments=len(analyzed_segments))

    timing.start_stage("persistence")
    try:
        _write_analysis_atomically(project_id, document)
    except Exception as exc:
        if preserve_existing:
            cleanup_partial_analysis_output(project_id)
        else:
            cleanup_analysis_output(project_id)
        raise AnalysisProcessError(
            _sanitize_error_message(f"Failed to save analysis: {exc}")
        ) from exc
    timing.end_stage("persistence")

    total_elapsed = time.perf_counter() - started
    log_timing_summary(
        project_id=project_id,
        pipeline="analysis",
        total_seconds=total_elapsed,
        provider=document.provider,
        segments=len(analyzed_segments),
        clip_candidates=clip_candidate_count,
        model_requests=timing.model_requests,
        cache_hits=timing.cache_hits,
    )
    return document


def analyze_transcript_segments_incrementally(project_id: str, *, chunk_index: int) -> AnalysisDocument | None:
    """Analyze one completed discovery chunk while later chunks may still be transcribing."""
    chunk_path = get_discovery_chunk_transcript_path(project_id, chunk_index)
    if not chunk_path.exists():
        return None

    chunk_document = TranscriptDocument.model_validate(json.loads(chunk_path.read_text(encoding="utf-8")))
    if not chunk_document.segments:
        return None

    provider = HeuristicAnalysisProvider()
    batch_size = max(1, settings.analysis_batch_size)
    analyzed_segments: list[SegmentAnalysis] = []
    if has_existing_analysis_output(project_id):
        existing = load_project_analysis(project_id)
        analyzed_segments = list(existing.segments)

    known_ids = {segment.segment_id for segment in analyzed_segments}
    pending_segments = [segment for segment in chunk_document.segments if segment.id not in known_ids]
    if not pending_segments:
        return load_project_analysis(project_id) if has_existing_analysis_output(project_id) else None

    for batch in batched(pending_segments, batch_size):
        batch_segments = list(batch)
        batch_results = extract_local_features(batch_segments)
        validated_batch = _validate_provider_output(batch_results)
        _validate_segment_alignment(batch_segments, validated_batch)
        for result in validated_batch:
            if result.segment_id not in known_ids:
                analyzed_segments.append(result)
                known_ids.add(result.segment_id)

    analyzed_segments.sort(key=lambda item: item.segment_id)
    is_heuristic = True
    clip_candidate_count = sum(1 for segment in analyzed_segments if segment.clip_candidate)
    transcript = load_workflow_transcript(project_id)
    document = AnalysisDocument(
        project_id=project_id,
        provider="heuristic",
        model="local-rules-v1",
        is_heuristic_fallback=is_heuristic,
        segment_count=len(analyzed_segments),
        clip_candidate_count=clip_candidate_count,
        segments=analyzed_segments,
    )
    _write_analysis_atomically(project_id, document)
    return document


def load_project_analysis(project_id: str) -> AnalysisDocument:
    load_project(project_id)

    analysis_path = get_analysis_output_path(project_id)
    if not analysis_path.exists() or not analysis_path.is_file():
        raise AnalysisNotFoundError(
            "Analysis not found. Run timeline analysis before loading results."
        )

    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
        return AnalysisDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AnalysisProcessError("Analysis file is corrupted.") from exc
