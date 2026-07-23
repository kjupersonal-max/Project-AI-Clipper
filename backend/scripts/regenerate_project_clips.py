from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.project import ProcessingStatus
from app.services.clip_selection import cleanup_clip_candidates_output, invalidate_stale_clip_candidates
from app.services.project_store import load_project, save_project


def regenerate_project(project_id: str) -> dict:
    invalidate_stale_clip_candidates(project_id)
    cleanup_clip_candidates_output(project_id)
    project = load_project(project_id)
    project.clip_selection_status = ProcessingStatus.PENDING
    project.clip_candidates_path = None
    project.clip_candidate_count = None
    save_project(project)

    client = TestClient(app)
    timings: dict[str, float] = {}

    started = time.perf_counter()
    transcribe = client.post(f"/api/projects/{project_id}/transcribe")
    timings["transcribe_seconds"] = round(time.perf_counter() - started, 3)
    if transcribe.status_code != 200:
        return {"error": "transcribe_failed", "detail": transcribe.text, "timings": timings}

    started = time.perf_counter()
    analyze = client.post(f"/api/projects/{project_id}/analyze")
    timings["analyze_seconds"] = round(time.perf_counter() - started, 3)
    if analyze.status_code != 200:
        return {"error": "analyze_failed", "detail": analyze.text, "timings": timings}

    started = time.perf_counter()
    select = client.post(f"/api/projects/{project_id}/select-clips", json={})
    timings["select_clips_seconds"] = round(time.perf_counter() - started, 3)
    if select.status_code != 200:
        return {"error": "select_failed", "detail": select.text, "timings": timings}

    candidates = client.get(f"/api/projects/{project_id}/clip-candidates")
    payload = candidates.json()
    durations = [candidate["duration"] for candidate in payload.get("candidates", [])]
    coverage = sum(candidate["duration"] for candidate in payload.get("candidates", []))
    source_duration = payload.get("source_duration_seconds") or 0.0
    coverage_pct = (coverage / source_duration * 100.0) if source_duration else 0.0

    return {
        "project_id": project_id,
        "timings": timings,
        "candidate_count": payload.get("candidate_count", 0),
        "durations": durations,
        "coverage_percent": round(coverage_pct, 2),
        "selection_pipeline_version": payload.get("selection_pipeline_version"),
    }


if __name__ == "__main__":
    project_id = sys.argv[1] if len(sys.argv) > 1 else "6dbfd514-90f0-4241-bf18-51c6de001ff2"
    print(json.dumps(regenerate_project(project_id), indent=2))
