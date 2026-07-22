from __future__ import annotations

from pydantic import ValidationError

from app.models.project import SegmentAnalysis, TranscriptSegment
from app.services.analysis.base import AnalysisProviderError


def validate_llm_segment_results(
    *,
    target_segments: list[TranscriptSegment],
    payload_segments: list[dict],
) -> list[SegmentAnalysis]:
    if not payload_segments:
        raise AnalysisProviderError("Analysis provider returned no segment results.")

    expected_ids = {segment.id for segment in target_segments}
    seen_ids: set[int] = set()
    results_by_id: dict[int, SegmentAnalysis] = {}

    for index, raw in enumerate(payload_segments):
        if not isinstance(raw, dict):
            raise AnalysisProviderError(
                f"Analysis provider returned invalid segment entry at index {index}."
            )

        segment_id = raw.get("segment_id")
        if not isinstance(segment_id, int):
            raise AnalysisProviderError(
                f"Analysis provider returned a segment without a valid segment_id at index {index}."
            )
        if segment_id in seen_ids:
            raise AnalysisProviderError(
                f"Analysis provider returned duplicate results for segment_id {segment_id}."
            )
        if segment_id not in expected_ids:
            raise AnalysisProviderError(
                f"Analysis provider returned unknown segment_id {segment_id}."
            )

        source = next(segment for segment in target_segments if segment.id == segment_id)
        try:
            validated = SegmentAnalysis.model_validate(
                {
                    "segment_id": segment_id,
                    "start": source.start,
                    "end": source.end,
                    "text": source.text.strip(),
                    "emotion": raw.get("emotion"),
                    "excitement_score": raw.get("excitement_score"),
                    "humor_score": raw.get("humor_score"),
                    "suspense_score": raw.get("suspense_score"),
                    "educational_score": raw.get("educational_score"),
                    "standalone_score": raw.get("standalone_score"),
                    "context_dependency_score": raw.get("context_dependency_score"),
                    "clip_candidate": raw.get("clip_candidate"),
                    "reason": raw.get("reason"),
                }
            )
        except ValidationError as exc:
            raise AnalysisProviderError(
                f"Analysis provider returned invalid scores for segment_id {segment_id}: {exc}"
            ) from exc

        seen_ids.add(segment_id)
        results_by_id[segment_id] = validated

    missing_ids = sorted(expected_ids - seen_ids)
    if missing_ids:
        raise AnalysisProviderError(
            "Analysis provider omitted results for segment_ids: "
            + ", ".join(str(segment_id) for segment_id in missing_ids)
            + "."
        )

    return [results_by_id[segment.id] for segment in target_segments]
