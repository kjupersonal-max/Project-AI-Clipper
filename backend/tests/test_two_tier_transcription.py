from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.project import ProcessingStatus, TranscriptDocument, TranscriptSegment, TranscriptTier
from app.services.timeline_analysis import analyze_project_timeline
from app.services.clip_selection import select_project_clips
from app.services.transcript_store import load_workflow_transcript


def _discovery_transcript(project_id: str) -> TranscriptDocument:
    return TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=120.0,
        segment_count=2,
        word_count=2,
        segments=[
            TranscriptSegment(id=0, start=0.0, end=2.0, text="hello world"),
            TranscriptSegment(id=1, start=2.0, end=4.0, text="great clip"),
        ],
        transcript_tier=TranscriptTier.DISCOVERY,
    )


def test_analyze_uses_discovery_transcript(sample_project, temp_backend_dirs):
    project_id = sample_project["project_id"]
    document = _discovery_transcript(project_id)
    discovery_path = temp_backend_dirs["transcripts_dir"] / project_id / "discovery_transcript.json"
    discovery_path.parent.mkdir(parents=True, exist_ok=True)
    discovery_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")

    project = sample_project["project"]
    project.transcription_status = ProcessingStatus.COMPLETED
    project.discovery_transcript_path = f"{project_id}/discovery_transcript.json"
    project.active_transcript_tier = TranscriptTier.DISCOVERY
    from app.services.project_store import save_project

    save_project(project)

    loaded = load_workflow_transcript(project_id)
    assert loaded.transcript_tier == TranscriptTier.DISCOVERY

    with patch("app.services.analysis_pipeline.resolve_analysis_provider") as mock_provider:
        from app.models.project import SegmentAnalysis

        provider = mock_provider.return_value
        provider.provider_name = "heuristic"
        provider.model_name = "heuristic"

        def analyze_batch(batch):
            return [
                SegmentAnalysis(
                    segment_id=segment.id,
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    emotion="neutral",
                    excitement_score=5.0,
                    humor_score=1.0,
                    suspense_score=1.0,
                    educational_score=1.0,
                    standalone_score=8.0,
                    context_dependency_score=2.0,
                    clip_candidate=True,
                    reason="Strong standalone moment",
                )
                for segment in batch
            ]

        provider.analyze_batch.side_effect = analyze_batch
        analysis = analyze_project_timeline(project_id)

    assert analysis.segment_count == 2


@patch("app.services.clip_retranscription.retranscribe_clip_range_for_captions")
@patch("app.services.clip_selection.load_project_analysis")
@patch("app.services.clip_selection.load_workflow_transcript")
def test_select_clips_can_use_discovery_transcript(
    mock_load_transcript,
    mock_load_analysis,
    mock_retranscribe,
    sample_project,
):
    project_id = sample_project["project_id"]
    mock_load_transcript.return_value = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=120.0,
        segment_count=5,
        word_count=5,
        segments=[
            TranscriptSegment(id=i, start=float(i * 4), end=float(i * 4 + 3.5), text=f"wow moment {i}")
            for i in range(5)
        ],
        transcript_tier=TranscriptTier.DISCOVERY,
    )
    from app.models.project import AnalysisDocument, SegmentAnalysis

    mock_load_analysis.return_value = AnalysisDocument(
        project_id=project_id,
        provider="heuristic",
        model="heuristic",
        is_heuristic_fallback=True,
        segment_count=5,
        clip_candidate_count=2,
        segments=[
            SegmentAnalysis(
                segment_id=i,
                start=float(i * 4),
                end=float(i * 4 + 3.5),
                text=f"wow moment {i}",
                emotion="excited",
                excitement_score=8.0,
                humor_score=2.0,
                suspense_score=2.0,
                educational_score=2.0,
                standalone_score=8.0,
                context_dependency_score=2.0,
                clip_candidate=True,
                reason="Strong hook",
            )
            for i in range(5)
        ],
    )

    project = sample_project["project"]
    project.transcription_status = ProcessingStatus.COMPLETED
    project.analysis_status = ProcessingStatus.COMPLETED
    from app.services.project_store import save_project

    save_project(project)

    with patch("app.services.clip_selection._source_duration", return_value=120.0):
        document = select_project_clips(
            project_id,
            min_score=0.0,
        )

    assert document.candidate_count >= 1
    assert all(candidate.duration >= 15.0 for candidate in document.candidates)
    mock_retranscribe.assert_not_called()
