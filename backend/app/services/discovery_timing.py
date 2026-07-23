from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - optional at runtime
    psutil = None  # type: ignore[assignment]


@dataclass
class DiscoveryStageRecord:
    stage: str
    wall_seconds: float
    percent_of_total: float = 0.0
    cache_hits: int = 0
    chunk_count: int = 0
    audio_seconds: float = 0.0
    real_time_factor: float | None = None
    thread_count: int = 0
    cpu_percent: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryBenchmarkReport:
    project_id: str
    audio_duration_seconds: float
    total_wall_seconds: float
    real_time_factor: float
    model: str
    device: str
    chunk_count: int
    cache_hits: int
    thread_count: int
    cpu_percent: float | None
    stages: list[DiscoveryStageRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "audio_duration_seconds": round(self.audio_duration_seconds, 3),
            "total_wall_seconds": round(self.total_wall_seconds, 3),
            "real_time_factor": round(self.real_time_factor, 3),
            "model": self.model,
            "device": self.device,
            "chunk_count": self.chunk_count,
            "cache_hits": self.cache_hits,
            "thread_count": self.thread_count,
            "cpu_percent": self.cpu_percent,
            "stages": [
                {
                    "stage": stage.stage,
                    "wall_seconds": round(stage.wall_seconds, 3),
                    "percent_of_total": round(stage.percent_of_total, 1),
                    "cache_hits": stage.cache_hits,
                    "chunk_count": stage.chunk_count,
                    "audio_seconds": round(stage.audio_seconds, 3),
                    "real_time_factor": (
                        round(stage.real_time_factor, 3)
                        if stage.real_time_factor is not None
                        else None
                    ),
                    "thread_count": stage.thread_count,
                    "cpu_percent": stage.cpu_percent,
                    **stage.extra,
                }
                for stage in self.stages
            ],
        }


class DiscoveryTimingCollector:
    """Collect per-stage wall times for discovery transcription benchmarks."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._started = time.perf_counter()
        self._stage_started: float | None = None
        self._current_stage: str | None = None
        self._records: list[DiscoveryStageRecord] = []

    def _snapshot_runtime(self) -> tuple[int, float | None]:
        thread_count = threading.active_count()
        cpu_percent: float | None = None
        if psutil is not None:
            cpu_percent = psutil.cpu_percent(interval=None)
        return thread_count, cpu_percent

    def start_stage(self, stage: str) -> None:
        if not self.enabled:
            return
        self._current_stage = stage
        self._stage_started = time.perf_counter()

    def end_stage(
        self,
        stage: str,
        *,
        cache_hits: int = 0,
        chunk_count: int = 0,
        audio_seconds: float = 0.0,
        **extra: Any,
    ) -> None:
        if not self.enabled or self._stage_started is None:
            return
        elapsed = time.perf_counter() - self._stage_started
        thread_count, cpu_percent = self._snapshot_runtime()
        rtf = elapsed / audio_seconds if audio_seconds > 0 else None
        self._records.append(
            DiscoveryStageRecord(
                stage=stage,
                wall_seconds=elapsed,
                cache_hits=cache_hits,
                chunk_count=chunk_count,
                audio_seconds=audio_seconds,
                real_time_factor=rtf,
                thread_count=thread_count,
                cpu_percent=cpu_percent,
                extra=extra,
            )
        )
        self._stage_started = None
        self._current_stage = None

    def record_stage(
        self,
        stage: str,
        wall_seconds: float,
        *,
        cache_hits: int = 0,
        chunk_count: int = 0,
        audio_seconds: float = 0.0,
        **extra: Any,
    ) -> None:
        if not self.enabled:
            return
        thread_count, cpu_percent = self._snapshot_runtime()
        rtf = wall_seconds / audio_seconds if audio_seconds > 0 else None
        self._records.append(
            DiscoveryStageRecord(
                stage=stage,
                wall_seconds=wall_seconds,
                cache_hits=cache_hits,
                chunk_count=chunk_count,
                audio_seconds=audio_seconds,
                real_time_factor=rtf,
                thread_count=thread_count,
                cpu_percent=cpu_percent,
                extra=extra,
            )
        )

    def build_report(
        self,
        *,
        project_id: str,
        audio_duration_seconds: float,
        model: str,
        device: str,
        chunk_count: int,
        cache_hits: int,
    ) -> DiscoveryBenchmarkReport:
        total = time.perf_counter() - self._started
        thread_count, cpu_percent = self._snapshot_runtime()
        stages: list[DiscoveryStageRecord] = []
        for record in self._records:
            percent = (record.wall_seconds / total * 100.0) if total > 0 else 0.0
            stages.append(
                DiscoveryStageRecord(
                    stage=record.stage,
                    wall_seconds=record.wall_seconds,
                    percent_of_total=percent,
                    cache_hits=record.cache_hits,
                    chunk_count=record.chunk_count,
                    audio_seconds=record.audio_seconds,
                    real_time_factor=record.real_time_factor,
                    thread_count=record.thread_count,
                    cpu_percent=record.cpu_percent,
                    extra=record.extra,
                )
            )
        return DiscoveryBenchmarkReport(
            project_id=project_id,
            audio_duration_seconds=audio_duration_seconds,
            total_wall_seconds=total,
            real_time_factor=total / max(audio_duration_seconds, 0.001),
            model=model,
            device=device,
            chunk_count=chunk_count,
            cache_hits=cache_hits,
            thread_count=thread_count,
            cpu_percent=cpu_percent,
            stages=stages,
        )
