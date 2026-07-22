from __future__ import annotations

import json
import shutil
from itertools import batched

from pydantic import ValidationError

from app.core.config import settings
from app.models.project import AnalysisDocument, SegmentAnalysis, TranscriptSegment
from app.services.analysis.base import AnalysisProviderError, ProviderConfigurationError
from app.services.analysis.registry import resolve_analysis_provider
from app.services.project_store import (
    get_analysis_output_dir,
    get_analysis_output_path,
    get_relative_analysis_path,
    load_project,
)
from app.services.transcription import (
    TranscriptNotFoundError,
    load_project_transcript,
)


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


def cleanup_analysis_output(project_id: str) -> None:
    analysis_dir = settings.analysis_dir / project_id
    partial_path = analysis_dir / f"{settings.analysis_output_filename}.part"
    if partial_path.exists():
        partial_path.unlink(missing_ok=True)

    output_path = analysis_dir / settings.analysis_output_filename
    if output_path.exists():
        output_path.unlink(missing_ok=True)

    if analysis_dir.exists() and not any(analysis_dir.iterdir()):
        shutil.rmtree(analysis_dir, ignore_errors=True)


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
        transcript = load_project_transcript(project_id)
    except TranscriptNotFoundError as exc:
        raise AnalysisTranscriptRequiredError(exc.message) from exc

    if not transcript.segments:
        raise InvalidTranscriptError("Transcript contains no segments to analyze.")

    return transcript


def analyze_project_timeline(project_id: str) -> AnalysisDocument:
    transcript = _require_completed_transcript(project_id)

    try:
        provider = resolve_analysis_provider()
    except ProviderConfigurationError:
        cleanup_analysis_output(project_id)
        raise

    analyzed_segments: list[SegmentAnalysis] = []
    batch_size = max(1, settings.analysis_batch_size)

    try:
        for batch in batched(transcript.segments, batch_size):
            batch_segments = list(batch)
            batch_results = provider.analyze_batch(batch_segments)
            validated_batch = _validate_provider_output(batch_results)
            _validate_segment_alignment(batch_segments, validated_batch)
            analyzed_segments.extend(validated_batch)
    except AnalysisProviderError:
        cleanup_analysis_output(project_id)
        raise
    except Exception as exc:
        cleanup_analysis_output(project_id)
        raise AnalysisProcessError(
            _sanitize_error_message(f"Timeline analysis failed: {exc}")
        ) from exc

    if not analyzed_segments:
        cleanup_analysis_output(project_id)
        raise AnalysisProcessError("Timeline analysis produced no segment results.")

    is_heuristic = provider.provider_name == "heuristic"
    clip_candidate_count = sum(1 for segment in analyzed_segments if segment.clip_candidate)
    document = AnalysisDocument(
        project_id=project_id,
        provider=provider.provider_name,
        model=provider.model_name,
        is_heuristic_fallback=is_heuristic,
        segment_count=len(analyzed_segments),
        clip_candidate_count=clip_candidate_count,
        segments=analyzed_segments,
    )

    try:
        _write_analysis_atomically(project_id, document)
    except Exception as exc:
        cleanup_analysis_output(project_id)
        raise AnalysisProcessError(
            _sanitize_error_message(f"Failed to save analysis: {exc}")
        ) from exc

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
