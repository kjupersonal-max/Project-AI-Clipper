from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.logging_config import configure_logging
from app.services.discovery_transcription import (
    benchmark_discovery_transcription,
    plan_audio_chunks,
    run_discovery_transcription,
)
from app.services.transcription import transcribe_project_audio
from app.services.transcription_config import resolve_discovery_settings, resolve_transcription_settings
from app.services.video_processing import inspect_video_file


def _format_result(label: str, *, elapsed: float, duration: float, segments: int, words: int, extra: dict | None = None) -> dict:
    payload = {
        "label": label,
        "wall_clock_seconds": round(elapsed, 3),
        "audio_duration_seconds": round(duration, 3),
        "real_time_factor": round(elapsed / max(duration, 0.001), 3),
        "segment_count": segments,
        "word_count": words,
    }
    if extra:
        payload.update(extra)
    return payload


def _clear_discovery_outputs(project_id: str) -> None:
    transcript_dir = Path("transcripts") / project_id
    if transcript_dir.exists():
        shutil.rmtree(transcript_dir, ignore_errors=True)


def benchmark_project(project_id: str, *, include_balanced: bool = False, clear_cache: bool = True) -> dict:
    from app.services.transcription import locate_project_audio

    configure_logging("INFO")
    audio_path = locate_project_audio(project_id)
    metadata = inspect_video_file(audio_path)
    duration = float(metadata.duration_seconds or 0.0)
    chunk_plans = plan_audio_chunks(duration=duration)
    discovery_settings = resolve_discovery_settings(language="en")
    results: dict[str, object] = {
        "project_id": project_id,
        "audio_duration_seconds": duration,
        "planned_chunks": len(chunk_plans),
        "discovery_model": discovery_settings.model_size,
        "runs": [],
        "stages": [],
    }

    if clear_cache:
        _clear_discovery_outputs(project_id)

    discovery_started = time.perf_counter()
    report = benchmark_discovery_transcription(project_id, language="en", use_cache=False)
    discovery_elapsed = time.perf_counter() - discovery_started
    results["runs"].append(
        _format_result(
            "discovery_optimized",
            elapsed=discovery_elapsed,
            duration=duration,
            segments=0,
            words=0,
            extra={
                "model": report.model,
                "device": report.device,
                "mode": "discovery",
                "thread_count": report.thread_count,
                "cpu_percent": report.cpu_percent,
            },
        )
    )
    results["stages"] = report.to_dict()["stages"]

    if clear_cache:
        _clear_discovery_outputs(project_id)

    cache_started = time.perf_counter()
    cached_report = benchmark_discovery_transcription(project_id, language="en", use_cache=True)
    cache_elapsed = time.perf_counter() - cache_started
    results["runs"].append(
        _format_result(
            "discovery_cache_hit",
            elapsed=cache_elapsed,
            duration=duration,
            segments=0,
            words=0,
            extra={
                "cache_hit": True,
                "thread_count": cached_report.thread_count,
            },
        )
    )

    if include_balanced:
        if clear_cache:
            _clear_discovery_outputs(project_id)
        balanced_settings = resolve_transcription_settings(quality_mode="balanced", language="en")
        balanced_started = time.perf_counter()
        balanced_document = transcribe_project_audio(project_id, quality_mode="balanced", use_full_quality=True)
        balanced_elapsed = time.perf_counter() - balanced_started
        results["runs"].append(
            _format_result(
                "balanced_full_vod",
                elapsed=balanced_elapsed,
                duration=duration,
                segments=balanced_document.segment_count,
                words=balanced_document.word_count,
                extra={
                    "model": balanced_settings.model_size,
                    "mode": "balanced",
                    "transcript_tier": balanced_document.transcript_tier.value,
                },
            )
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark discovery transcription stages.")
    parser.add_argument("project_id", help="Project ID with extracted audio available")
    parser.add_argument("--skip-balanced", action="store_true", help="Skip full balanced VOD benchmark")
    parser.add_argument("--keep-cache", action="store_true", help="Do not clear discovery outputs between runs")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    results = benchmark_project(
        args.project_id,
        include_balanced=not args.skip_balanced,
        clear_cache=not args.keep_cache,
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
