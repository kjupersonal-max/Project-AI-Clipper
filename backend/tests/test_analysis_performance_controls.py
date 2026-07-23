from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.project import TranscriptSegment
from app.services.analysis_cache import load_cached_window_analysis, store_cached_window_analysis, window_cache_key
from app.services.analysis_pipeline import build_semantic_windows, run_hierarchical_analysis, score_semantic_windows
from app.services.analysis_timing import AnalysisTimingCollector
from app.services.clip_selection import select_project_clips
from app.services.timeline_analysis import analyze_project_timeline


def test_analysis_never_retranscribes(sample_project, temp_backend_dirs, monkeypatch):
    project_id = sample_project["project_id"]
    segments = [
        TranscriptSegment(id=i, start=float(i * 3), end=float(i * 3 + 2), text=f"wow segment {i}", words=[])
        for i in range(8)
    ]
    from tests.test_clip_selection import _write_completed_transcript

    _write_completed_transcript(sample_project, temp_backend_dirs, segments)

    with patch("app.services.transcription.transcribe_project_audio") as mock_transcribe:
        with patch("app.services.transcription._load_whisper_model") as mock_whisper:
            analyze_project_timeline(project_id)
    mock_transcribe.assert_not_called()
    mock_whisper.assert_not_called()


def test_limited_deep_analysis_window_count():
    segments = [
        TranscriptSegment(id=i, start=float(i * 30), end=float(i * 30 + 25), text=f"insane moment {i}!", words=[])
        for i in range(12)
    ]
    request_counter = {"count": 0}

    class CountingProvider:
        provider_name = "openai"
        model_name = "test-model"

        def bind_transcript(self, _segments):
            return None

        def analyze_batch(self, batch):
            request_counter["count"] += 1
            from app.services.analysis.heuristic import HeuristicAnalysisProvider

            return HeuristicAnalysisProvider().analyze_batch(batch)

    with patch("app.services.analysis_pipeline.resolve_analysis_provider", return_value=CountingProvider()):
        with patch.object(settings, "analysis_max_deep_windows", 3):
            with patch.object(settings, "analysis_max_model_requests", 4):
                run_hierarchical_analysis(project_id="limit-test", segments=segments)
    assert request_counter["count"] <= 4


def test_window_cache_resume():
    segments = [TranscriptSegment(id=0, start=0.0, end=10.0, text="No way, that was insane!", words=[])]
    from app.services.analysis.heuristic import HeuristicAnalysisProvider

    results = HeuristicAnalysisProvider().analyze_batch(segments)
    cache_key = window_cache_key(
        transcript_key="abc123",
        window_start=0.0,
        window_end=180.0,
        tier="discovery",
    )
    store_cached_window_analysis(cache_key, "cache-test", results)
    cached = load_cached_window_analysis(cache_key, "cache-test")
    assert cached is not None
    assert cached[0].segment_id == 0


def test_semantic_window_count_bounded_for_long_transcript():
    segments = [
        TranscriptSegment(id=i, start=float(i * 5), end=float(i * 5 + 4), text=f"segment {i}", words=[])
        for i in range(500)
    ]
    windows = build_semantic_windows(segments, window_seconds=180.0, overlap_seconds=30.0)
    assert len(windows) < 100


def test_progress_stages_are_reported():
    segments = [TranscriptSegment(id=i, start=float(i * 4), end=float(i * 4 + 3), text=f"wow {i}", words=[]) for i in range(6)]
    stages: list[str] = []

    def progress(stage: str, percent: float, detail: str) -> None:
        stages.append(stage)

    run_hierarchical_analysis(
        project_id="progress-test",
        segments=segments,
        progress_callback=progress,
    )
    assert "extracting_features" in stages
    assert "building_windows" in stages
    assert "completed" in stages
