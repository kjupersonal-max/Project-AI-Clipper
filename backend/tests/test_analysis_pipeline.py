from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.project import TranscriptSegment
from app.services.analysis_pipeline import (
    AnalysisTimeoutError,
    build_semantic_windows,
    extract_local_features,
    run_hierarchical_analysis,
)
from app.services.analysis_timing import AnalysisTimingCollector


def test_extract_local_features_does_not_load_whisper():
    segments = [
        TranscriptSegment(id=0, start=0.0, end=5.0, text="Wait, that was insane!", words=[]),
        TranscriptSegment(id=1, start=5.0, end=10.0, text="Because this tip helps you learn", words=[]),
    ]
    with patch("app.services.transcription._load_whisper_model") as mock_load:
        results = extract_local_features(segments)
    mock_load.assert_not_called()
    assert len(results) == 2


def test_build_semantic_windows_skips_empty_speech():
    segments = [
        TranscriptSegment(id=0, start=0.0, end=1.0, text="hi", words=[]),
    ]
    windows = build_semantic_windows(segments, window_seconds=180.0, min_speech_seconds=20.0)
    assert windows == []


def test_hierarchical_analysis_limits_deep_windows():
    project_id = "test-project"
    segments = [
        TranscriptSegment(id=i, start=float(i * 5), end=float(i * 5 + 4), text=f"segment {i} wow!", words=[])
        for i in range(40)
    ]

    class CountingProvider:
        provider_name = "openai"
        model_name = "test-model"

        def bind_transcript(self, _segments):
            return None

        def analyze_batch(self, batch):
            from app.services.analysis.heuristic import HeuristicAnalysisProvider

            return HeuristicAnalysisProvider().analyze_batch(batch)

    with patch("app.services.analysis_pipeline.resolve_analysis_provider", return_value=CountingProvider()):
        with patch.object(settings, "analysis_max_deep_windows", 2):
            with patch.object(settings, "analysis_max_model_requests", 3):
                analyzed, provider, _, _ = run_hierarchical_analysis(
                    project_id=project_id,
                    segments=segments,
                    timing_collector=AnalysisTimingCollector(enabled=True),
                )
    assert provider == "openai"
    assert len(analyzed) == 40


def test_analysis_timeout_raises():
    project_id = "test-project"
    segments = [TranscriptSegment(id=0, start=0.0, end=5.0, text="hello", words=[])]

    with patch.object(settings, "analysis_total_timeout_seconds", 0.001):
        with patch("app.services.analysis_pipeline.time.perf_counter") as mock_clock:
            mock_clock.side_effect = [1000.0, 1000.0, 1000.1]
            with pytest.raises(AnalysisTimeoutError):
                run_hierarchical_analysis(project_id=project_id, segments=segments)


def test_hierarchical_analysis_uses_heuristic_without_api_key():
    project_id = "test-project"
    segments = [
        TranscriptSegment(id=i, start=float(i * 4), end=float(i * 4 + 3), text=f"segment {i}", words=[])
        for i in range(12)
    ]
    with patch("app.services.analysis_pipeline.resolve_analysis_provider") as mock_resolve:
        from app.services.analysis.heuristic import HeuristicAnalysisProvider

        mock_resolve.return_value = HeuristicAnalysisProvider()
        analyzed, provider, _, is_heuristic = run_hierarchical_analysis(
            project_id=project_id,
            segments=segments,
            timing_collector=AnalysisTimingCollector(enabled=True),
        )
    assert provider == "heuristic"
    assert is_heuristic is True
    assert len(analyzed) == 12
