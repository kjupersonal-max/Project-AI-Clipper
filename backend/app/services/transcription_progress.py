from __future__ import annotations

from enum import Enum
from typing import Callable, Protocol


class TranscriptionStage(str, Enum):
    PREPARING_AUDIO = "preparing_audio"
    LOADING_MODEL = "loading_model"
    PRIMARY_TRANSCRIPTION = "primary_transcription"
    EVALUATING_QUALITY = "evaluating_quality"
    SECONDARY_TRANSCRIPTION = "secondary_transcription"
    RECOVERY_PASS = "recovery_pass"
    MERGING_TRANSCRIPT = "merging_transcript"
    COMPLETED = "completed"


class AnalysisStage(str, Enum):
    PREPARING = "preparing"
    WINDOW_ANALYSIS = "window_analysis"
    MERGING_RESULTS = "merging_results"
    COMPLETED = "completed"


class ClipSelectionStage(str, Enum):
    PREPARING = "preparing"
    BUILDING_CANDIDATES = "building_candidates"
    SCORING = "scoring"
    DEDUPLICATING = "deduplicating"
    COMPLETED = "completed"


STAGE_BASE_PROGRESS: dict[str, float] = {
    TranscriptionStage.PREPARING_AUDIO.value: 5.0,
    TranscriptionStage.LOADING_MODEL.value: 10.0,
    TranscriptionStage.PRIMARY_TRANSCRIPTION.value: 35.0,
    TranscriptionStage.EVALUATING_QUALITY.value: 45.0,
    TranscriptionStage.SECONDARY_TRANSCRIPTION.value: 60.0,
    TranscriptionStage.RECOVERY_PASS.value: 80.0,
    TranscriptionStage.MERGING_TRANSCRIPT.value: 92.0,
    TranscriptionStage.COMPLETED.value: 100.0,
}


class ProgressReporter(Protocol):
    def __call__(self, stage: str, progress_pct: float, detail: str = "") -> None: ...


def noop_progress(_stage: str, _progress_pct: float, _detail: str = "") -> None:
    return None


def stage_progress(stage: TranscriptionStage | str, *, sub_progress: float = 0.0) -> float:
    key = stage.value if isinstance(stage, TranscriptionStage) else stage
    base = STAGE_BASE_PROGRESS.get(key, 0.0)
    next_keys = list(STAGE_BASE_PROGRESS.keys())
    try:
        index = next_keys.index(key)
        ceiling = STAGE_BASE_PROGRESS[next_keys[index + 1]] if index + 1 < len(next_keys) else 100.0
    except ValueError:
        ceiling = 100.0
    span = max(0.0, ceiling - base)
    return round(min(100.0, base + span * max(0.0, min(1.0, sub_progress))), 1)
