from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.project import SegmentAnalysis


def _analysis_cache_dir(project_id: str) -> Path:
    cache_dir = settings.analysis_dir / project_id / "_analysis_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def transcript_hash(segments: list[Any]) -> str:
    payload = json.dumps(
        [(segment.id, round(segment.start, 3), round(segment.end, 3), segment.text.strip()) for segment in segments],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def window_cache_key(
    *,
    transcript_key: str,
    window_start: float,
    window_end: float,
    tier: str,
) -> str:
    raw = f"{transcript_key}:{tier}:{window_start:.3f}:{window_end:.3f}:{settings.analysis_pipeline_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cached_window_analysis(cache_key: str, project_id: str) -> list[SegmentAnalysis] | None:
    path = _analysis_cache_dir(project_id) / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [SegmentAnalysis.model_validate(item) for item in payload]
    except (json.JSONDecodeError, ValueError):
        return None


def store_cached_window_analysis(
    cache_key: str,
    project_id: str,
    segments: list[SegmentAnalysis],
) -> None:
    path = _analysis_cache_dir(project_id) / f"{cache_key}.json"
    path.write_text(
        json.dumps([segment.model_dump(mode="json") for segment in segments], separators=(",", ":")),
        encoding="utf-8",
    )
