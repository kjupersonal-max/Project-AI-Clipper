from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("app.pipeline.timing")


def _format_kv(**fields: Any) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


def log_stage_event(
    stage: str,
    event: str,
    *,
    project_id: str | None = None,
    elapsed_seconds: float | None = None,
    **fields: Any,
) -> None:
    payload = _format_kv(project_id=project_id, stage=stage, event=event, **fields)
    if elapsed_seconds is not None:
        payload = f"{payload} elapsed={elapsed_seconds:.3f}s"
    logger.info(payload)


@contextmanager
def timed_stage(
    stage: str,
    *,
    project_id: str | None = None,
    **fields: Any,
) -> Iterator[dict[str, Any]]:
    started = time.perf_counter()
    log_stage_event(stage, "start", project_id=project_id, **fields)
    metrics: dict[str, Any] = {}
    try:
        yield metrics
    finally:
        elapsed = time.perf_counter() - started
        metrics["elapsed_seconds"] = round(elapsed, 3)
        log_stage_event(
            stage,
            "end",
            project_id=project_id,
            elapsed_seconds=elapsed,
            **fields,
            **{k: v for k, v in metrics.items() if k != "elapsed_seconds"},
        )


def log_timing_summary(
    *,
    project_id: str | None,
    pipeline: str,
    total_seconds: float,
    **fields: Any,
) -> None:
    logger.info(
        "%s",
        _format_kv(
            project_id=project_id,
            pipeline=pipeline,
            total=f"{total_seconds:.3f}s",
            **fields,
        ),
    )


def log_transcription_trace(
    *,
    event: str,
    endpoint: str | None = None,
    project_id: str | None = None,
    transcription_tier: str | None = None,
    transcription_path: str | None = None,
    model_name: str | None = None,
    use_full_quality: bool | None = None,
    chunk_count: int | None = None,
    model_load_seconds: float | None = None,
    transcription_seconds: float | None = None,
    persistence_seconds: float | None = None,
    total_wall_seconds: float | None = None,
    **fields: Any,
) -> None:
    """Structured end-to-end transcription trace for UI/API debugging."""
    logger.info(
        "transcription_trace %s",
        _format_kv(
            event=event,
            endpoint=endpoint,
            project_id=project_id,
            transcription_tier=transcription_tier,
            transcription_path=transcription_path,
            model_name=model_name,
            use_full_quality=use_full_quality,
            chunk_count=chunk_count,
            model_load_seconds=(
                f"{model_load_seconds:.3f}s" if model_load_seconds is not None else None
            ),
            transcription_seconds=(
                f"{transcription_seconds:.3f}s" if transcription_seconds is not None else None
            ),
            persistence_seconds=(
                f"{persistence_seconds:.3f}s" if persistence_seconds is not None else None
            ),
            total_wall_seconds=(
                f"{total_wall_seconds:.3f}s" if total_wall_seconds is not None else None
            ),
            **fields,
        ),
    )
