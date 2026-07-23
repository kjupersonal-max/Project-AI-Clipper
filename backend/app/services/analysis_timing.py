from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


@dataclass
class AnalysisStageRecord:
    stage: str
    wall_seconds: float
    percent_of_total: float = 0.0
    windows: int = 0
    candidates_in: int = 0
    candidates_out: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    model_requests: int = 0
    retries: int = 0
    timeouts: int = 0
    provider: str | None = None
    thread_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisBenchmarkReport:
    project_id: str
    audio_duration_seconds: float
    total_wall_seconds: float
    stages: list[AnalysisStageRecord] = field(default_factory=list)
    model_requests: int = 0
    deep_windows: int = 0
    cache_hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "audio_duration_seconds": round(self.audio_duration_seconds, 3),
            "total_wall_seconds": round(self.total_wall_seconds, 3),
            "model_requests": self.model_requests,
            "deep_windows": self.deep_windows,
            "cache_hits": self.cache_hits,
            "stages": [
                {
                    "stage": stage.stage,
                    "wall_seconds": round(stage.wall_seconds, 3),
                    "percent_of_total": round(stage.percent_of_total, 1),
                    "windows": stage.windows,
                    "candidates_in": stage.candidates_in,
                    "candidates_out": stage.candidates_out,
                    "cache_hits": stage.cache_hits,
                    "cache_misses": stage.cache_misses,
                    "model_requests": stage.model_requests,
                    "retries": stage.retries,
                    "timeouts": stage.timeouts,
                    "provider": stage.provider,
                    "thread_count": stage.thread_count,
                    **stage.extra,
                }
                for stage in self.stages
            ],
        }


class AnalysisTimingCollector:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._started = time.perf_counter()
        self._stage_started: float | None = None
        self._records: list[AnalysisStageRecord] = []
        self.model_requests = 0
        self.retries = 0
        self.timeouts = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def start_stage(self, stage: str) -> None:
        if not self.enabled:
            return
        self._stage_started = time.perf_counter()

    def end_stage(self, stage: str, **fields: Any) -> None:
        if not self.enabled or self._stage_started is None:
            return
        elapsed = time.perf_counter() - self._stage_started
        thread_count = threading.active_count()
        self._records.append(
            AnalysisStageRecord(
                stage=stage,
                wall_seconds=elapsed,
                thread_count=thread_count,
                model_requests=fields.pop("model_requests", 0),
                retries=fields.pop("retries", 0),
                timeouts=fields.pop("timeouts", 0),
                cache_hits=fields.pop("cache_hits", 0),
                cache_misses=fields.pop("cache_misses", 0),
                windows=fields.pop("windows", 0),
                candidates_in=fields.pop("candidates_in", 0),
                candidates_out=fields.pop("candidates_out", 0),
                provider=fields.pop("provider", None),
                extra=fields,
            )
        )
        self._stage_started = None

    def build_report(
        self,
        *,
        project_id: str,
        audio_duration_seconds: float,
        deep_windows: int,
    ) -> AnalysisBenchmarkReport:
        total = time.perf_counter() - self._started
        stages: list[AnalysisStageRecord] = []
        for record in self._records:
            percent = (record.wall_seconds / total * 100.0) if total > 0 else 0.0
            stages.append(
                AnalysisStageRecord(
                    stage=record.stage,
                    wall_seconds=record.wall_seconds,
                    percent_of_total=percent,
                    windows=record.windows,
                    candidates_in=record.candidates_in,
                    candidates_out=record.candidates_out,
                    cache_hits=record.cache_hits,
                    cache_misses=record.cache_misses,
                    model_requests=record.model_requests,
                    retries=record.retries,
                    timeouts=record.timeouts,
                    provider=record.provider,
                    thread_count=record.thread_count,
                    extra=record.extra,
                )
            )
        return AnalysisBenchmarkReport(
            project_id=project_id,
            audio_duration_seconds=audio_duration_seconds,
            total_wall_seconds=total,
            stages=stages,
            model_requests=self.model_requests,
            deep_windows=deep_windows,
            cache_hits=self.cache_hits,
        )
