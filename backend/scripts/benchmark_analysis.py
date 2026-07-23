from __future__ import annotations

import json
import shutil
import sys
import time
import wave
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.logging_config import configure_logging
from app.models.project import ProcessingStatus
from app.services.analysis_timing import AnalysisTimingCollector
from app.services.clip_selection import select_project_clips
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import analyze_project_timeline


def _audio_duration_seconds(project_id: str) -> float:
    audio_path = Path("audio") / project_id / "audio.wav"
    if not audio_path.exists():
        return 0.0
    with wave.open(str(audio_path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def benchmark_analysis(project_id: str, *, use_cache: bool = True) -> dict:
    configure_logging("WARNING")
    if not use_cache:
        shutil.rmtree(Path("analysis") / project_id, ignore_errors=True)
        shutil.rmtree(Path("analysis_cache") / project_id, ignore_errors=True)
    shutil.rmtree(Path("clip_candidates") / project_id, ignore_errors=True)

    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.analysis_status = ProcessingStatus.PROCESSING
    save_project(project)

    timing = AnalysisTimingCollector(enabled=True)
    analysis_started = time.perf_counter()
    document = analyze_project_timeline(project_id, timing_collector=timing)
    analysis_elapsed = time.perf_counter() - analysis_started

    project = load_project(project_id)
    project.analysis_status = ProcessingStatus.COMPLETED
    project.analysis_provider = document.provider
    save_project(project)

    selection_started = time.perf_counter()
    candidates = select_project_clips(project_id, min_score=0.0)
    selection_elapsed = time.perf_counter() - selection_started

    deep_windows = sum(
        1
        for stage in timing._records
        if stage.stage == "deep_analysis"
    )
    report = timing.build_report(
        project_id=project_id,
        audio_duration_seconds=_audio_duration_seconds(project_id),
        deep_windows=deep_windows,
    )
    payload = report.to_dict()
    payload["analysis_wall_seconds"] = round(analysis_elapsed, 3)
    payload["clip_selection_wall_seconds"] = round(selection_elapsed, 3)
    payload["total_wall_seconds"] = round(analysis_elapsed + selection_elapsed, 3)
    payload["candidate_count"] = candidates.candidate_count
    payload["clip_candidate_segments"] = document.clip_candidate_count
    payload["analysis_provider"] = document.provider
    payload["used_cache"] = use_cache
    return payload


if __name__ == "__main__":
    project_id = sys.argv[1] if len(sys.argv) > 1 else "6dbfd514-90f0-4241-bf18-51c6de001ff2"
    cold = benchmark_analysis(project_id, use_cache=False)
    warm = benchmark_analysis(project_id, use_cache=True)
    print(
        json.dumps(
            {
                "cold_run": cold,
                "warm_run": warm,
            },
            indent=2,
        )
    )
