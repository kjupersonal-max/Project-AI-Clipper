from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from itertools import batched
from typing import Callable

from app.core.config import settings
from app.models.project import SegmentAnalysis, TranscriptSegment
from app.services.analysis.base import AnalysisProvider, AnalysisProviderError, ProviderConfigurationError
from app.services.analysis.heuristic import HeuristicAnalysisProvider
from app.services.analysis.registry import resolve_analysis_provider
from app.services.analysis_cache import (
    load_cached_window_analysis,
    store_cached_window_analysis,
    transcript_hash,
    window_cache_key,
)
from app.services.analysis_timing import AnalysisTimingCollector

logger = logging.getLogger(__name__)


class AnalysisPipelineError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AnalysisTimeoutError(AnalysisPipelineError):
    def __init__(self, message: str, *, stage: str):
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class SemanticWindow:
    index: int
    start: float
    end: float
    segments: tuple[TranscriptSegment, ...]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def speech_seconds(self) -> float:
        return sum(max(0.0, segment.end - segment.start) for segment in self.segments)


@dataclass(frozen=True)
class WindowScore:
    window: SemanticWindow
    score: float
    candidate_density: float
    peak_engagement: float


def _check_deadline(deadline: float | None, stage: str) -> None:
    if deadline is not None and time.perf_counter() >= deadline:
        raise AnalysisTimeoutError(f"Analysis timed out during {stage}.", stage=stage)


def build_semantic_windows(
    segments: list[TranscriptSegment],
    *,
    window_seconds: float | None = None,
    overlap_seconds: float | None = None,
    min_speech_seconds: float | None = None,
) -> list[SemanticWindow]:
    if not segments:
        return []

    window_size = window_seconds or settings.analysis_semantic_window_seconds
    overlap = overlap_seconds or settings.analysis_semantic_window_overlap_seconds
    min_speech = min_speech_seconds or settings.analysis_min_window_speech_seconds
    duration = max(segment.end for segment in segments)
    stride = max(30.0, window_size - overlap)
    windows: list[SemanticWindow] = []
    start = 0.0
    index = 0
    while start < duration:
        end = min(duration, start + window_size)
        window_segments = tuple(
            segment
            for segment in segments
            if segment.end > start and segment.start < end
        )
        if window_segments:
            window = SemanticWindow(index=index, start=start, end=end, segments=window_segments)
            if window.speech_seconds >= min_speech:
                windows.append(window)
            index += 1
        if end >= duration:
            break
        start += stride
    if windows:
        return windows
    total_speech = sum(max(0.0, segment.end - segment.start) for segment in segments)
    if total_speech >= min_speech:
        return [
            SemanticWindow(
                index=0,
                start=0.0,
                end=duration,
                segments=tuple(segments),
            )
        ]
    return []


def extract_local_features(segments: list[TranscriptSegment]) -> list[SegmentAnalysis]:
    provider = HeuristicAnalysisProvider()
    return provider.analyze_batch(segments)


def score_semantic_windows(
    windows: list[SemanticWindow],
    analyzed_segments: dict[int, SegmentAnalysis],
) -> list[WindowScore]:
    scored: list[WindowScore] = []
    for window in windows:
        window_analysis = [analyzed_segments[segment.id] for segment in window.segments if segment.id in analyzed_segments]
        if not window_analysis:
            continue
        candidate_count = sum(1 for segment in window_analysis if segment.clip_candidate)
        candidate_density = candidate_count / max(1, len(window_analysis))
        peak_engagement = max(
            max(segment.excitement_score, segment.humor_score, segment.suspense_score, segment.educational_score)
            for segment in window_analysis
        )
        average_standalone = sum(segment.standalone_score for segment in window_analysis) / len(window_analysis)
        score = peak_engagement * 3.0 + candidate_density * 20.0 + average_standalone * 1.5
        scored.append(
            WindowScore(
                window=window,
                score=score,
                candidate_density=candidate_density,
                peak_engagement=peak_engagement,
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _merge_segment_results(
    base: dict[int, SegmentAnalysis],
    updates: list[SegmentAnalysis],
) -> None:
    for segment in updates:
        existing = base.get(segment.segment_id)
        if existing is None:
            base[segment.segment_id] = segment
            continue
        existing_peak = max(
            existing.excitement_score,
            existing.humor_score,
            existing.suspense_score,
            existing.educational_score,
        )
        update_peak = max(
            segment.excitement_score,
            segment.humor_score,
            segment.suspense_score,
            segment.educational_score,
        )
        if update_peak >= existing_peak or segment.clip_candidate and not existing.clip_candidate:
            base[segment.segment_id] = segment


def _deep_analyze_window(
    *,
    window: SemanticWindow,
    deep_provider: AnalysisProvider,
    transcript_key: str,
    project_id: str,
    tier: str,
    timing: AnalysisTimingCollector,
    deadline: float | None,
    request_budget: int | None = None,
) -> list[SegmentAnalysis]:
    _check_deadline(deadline, "deep_analysis")
    cache_key = window_cache_key(
        transcript_key=transcript_key,
        window_start=window.start,
        window_end=window.end,
        tier=tier,
    )
    cached = load_cached_window_analysis(cache_key, project_id)
    if cached is not None:
        timing.cache_hits += 1
        return cached

    timing.cache_misses += 1
    if hasattr(deep_provider, "bind_transcript"):
        deep_provider.bind_transcript(list(window.segments))

    results: list[SegmentAnalysis] = []
    batch_size = max(1, settings.analysis_batch_size)
    for batch in batched(window.segments, batch_size):
        if request_budget is not None and timing.model_requests >= request_budget:
            break
        _check_deadline(deadline, "deep_analysis")
        batch_segments = list(batch)
        timing.model_requests += 1
        batch_results = deep_provider.analyze_batch(batch_segments)
        results.extend(batch_results)

    if results:
        store_cached_window_analysis(cache_key, project_id, results)
    return results


def run_hierarchical_analysis(
    *,
    project_id: str,
    segments: list[TranscriptSegment],
    transcript_tier: str = "discovery",
    progress_callback: Callable[[str, float, str], None] | None = None,
    timing_collector: AnalysisTimingCollector | None = None,
) -> tuple[list[SegmentAnalysis], str, str | None, bool]:
    timing = timing_collector or AnalysisTimingCollector(enabled=False)
    deadline = time.perf_counter() + settings.analysis_total_timeout_seconds
    _check_deadline(deadline, "endpoint_entry")
    transcript_key = transcript_hash(segments)

    def report(stage: str, percent: float, detail: str) -> None:
        if progress_callback is not None:
            progress_callback(stage, percent, detail)

    timing.start_stage("loading_transcript")
    report("loading_transcript", 5.0, "Transcript loaded.")
    timing.start_stage("transcript_normalization")
    normalized_segments = list(segments)
    timing.end_stage("transcript_normalization", segments=len(normalized_segments))
    timing.start_stage("transcript_hash")
    timing.end_stage("transcript_hash", segments=len(normalized_segments))
    timing.end_stage("loading_transcript", segments=len(normalized_segments))

    timing.start_stage("extracting_features")
    report("extracting_features", 10.0, "Running local feature extraction.")
    local_results = extract_local_features(normalized_segments)
    analyzed_by_id = {segment.segment_id: segment for segment in local_results}
    timing.end_stage("extracting_features", segments=len(local_results), provider="heuristic")

    timing.start_stage("building_windows")
    report("building_windows", 20.0, "Building semantic windows.")
    windows = build_semantic_windows(normalized_segments)
    timing.end_stage("building_windows", windows=len(windows))

    timing.start_stage("selecting_promising_windows")
    report("selecting_promising_windows", 30.0, "Scoring semantic windows.")
    scored_windows = score_semantic_windows(windows, analyzed_by_id)
    max_deep = max(0, settings.analysis_max_deep_windows)
    promising = scored_windows[:max_deep]
    timing.end_stage(
        "selecting_promising_windows",
        windows=len(windows),
        candidates_in=len(scored_windows),
        candidates_out=len(promising),
    )

    deep_provider: AnalysisProvider | None = None
    provider_name = "heuristic"
    model_name: str | None = "local-rules-v1"
    is_heuristic = True
    try:
        candidate_provider = resolve_analysis_provider()
        if candidate_provider.provider_name != "heuristic":
            deep_provider = candidate_provider
            provider_name = candidate_provider.provider_name
            model_name = candidate_provider.model_name
            is_heuristic = False
    except ProviderConfigurationError:
        deep_provider = None

    if deep_provider is not None and promising:
        timing.start_stage("deep_analysis")
        report("deep_analysis", 45.0, f"Deep analysis on {len(promising)} windows.")
        request_budget = max(0, settings.analysis_max_model_requests)
        completed_windows = 0
        worker_count = max(1, settings.analysis_deep_worker_count)

        def analyze_one(score: WindowScore) -> tuple[int, list[SegmentAnalysis]]:
            return score.window.index, _deep_analyze_window(
                window=score.window,
                deep_provider=deep_provider,
                transcript_key=transcript_key,
                project_id=project_id,
                tier=transcript_tier,
                timing=timing,
                deadline=deadline,
                request_budget=request_budget,
            )

        if worker_count <= 1:
            for score in promising:
                if timing.model_requests >= request_budget:
                    break
                _check_deadline(deadline, "deep_analysis")
                try:
                    _, updates = analyze_one(score)
                except AnalysisProviderError as exc:
                    timing.retries += 1
                    logger.warning("Deep analysis window failed: %s", exc)
                    continue
                _merge_segment_results(analyzed_by_id, updates)
                completed_windows += 1
                report(
                    "deep_analysis",
                    45.0 + (completed_windows / max(1, len(promising))) * 35.0,
                    f"Deep analysis window {completed_windows}/{len(promising)}",
                )
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(analyze_one, score): score
                    for score in promising
                }
                for future in as_completed(futures):
                    _check_deadline(deadline, "deep_analysis")
                    try:
                        _, updates = future.result(timeout=settings.analysis_window_timeout_seconds)
                    except FuturesTimeoutError:
                        timing.timeouts += 1
                        logger.warning("Deep analysis window timed out.")
                        continue
                    except AnalysisProviderError as exc:
                        timing.retries += 1
                        logger.warning("Deep analysis window failed: %s", exc)
                        continue
                    _merge_segment_results(analyzed_by_id, updates)
                    completed_windows += 1
                    report(
                        "deep_analysis",
                        45.0 + (completed_windows / max(1, len(promising))) * 35.0,
                        f"Deep analysis window {completed_windows}/{len(promising)}",
                    )

        timing.end_stage(
            "deep_analysis",
            windows=completed_windows,
            model_requests=timing.model_requests,
            provider=provider_name,
            cache_hits=timing.cache_hits,
            cache_misses=timing.cache_misses,
        )
    else:
        report("deep_analysis", 80.0, "Skipped deep analysis; using local features only.")

    analyzed_segments = [analyzed_by_id[segment.id] for segment in normalized_segments if segment.id in analyzed_by_id]
    analyzed_segments.sort(key=lambda item: item.segment_id)
    report("completed", 100.0, "Analysis complete.")
    return analyzed_segments, provider_name, model_name, is_heuristic
