from __future__ import annotations

import hashlib
import re

from app.models.project import SegmentAnalysis, TranscriptSegment
from app.services.analysis.base import AnalysisProvider

EXCITEMENT_PATTERNS = (
    "!",
    "wow",
    "insane",
    "crazy",
    "clutch",
    "let's go",
    "lets go",
    "no way",
    "holy",
)
HUMOR_PATTERNS = ("lol", "haha", "funny", "joke", "lmao", "rofl")
SUSPENSE_PATTERNS = ("wait", "watch out", "careful", "hold on", "almost", "close")
EDUCATIONAL_PATTERNS = (
    "because",
    "how to",
    "tip",
    "learn",
    "means",
    "reason",
    "explain",
    "actually",
)
CONTEXT_PATTERNS = (
    "earlier",
    "before",
    "remember",
    "that guy",
    "again",
    "like i said",
    "as i mentioned",
    "continuing",
)
EMOTIONS = (
    "neutral",
    "excited",
    "humorous",
    "tense",
    "informative",
    "surprised",
    "frustrated",
)


def _count_pattern_hits(text: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if pattern in text)


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 1)


def _deterministic_jitter(text: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{text}".encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 21) / 10.0


class HeuristicAnalysisProvider(AnalysisProvider):
    @property
    def provider_name(self) -> str:
        return "heuristic"

    @property
    def model_name(self) -> str | None:
        return "local-rules-v1"

    def analyze_batch(self, segments: list[TranscriptSegment]) -> list[SegmentAnalysis]:
        return [self._analyze_segment(segment) for segment in segments]

    def _analyze_segment(self, segment: TranscriptSegment) -> SegmentAnalysis:
        text = segment.text.strip()
        lowered = text.lower()
        exclamation_count = text.count("!")
        question_count = text.count("?")
        word_count = len(re.findall(r"\b\w+\b", text))

        excitement = _clamp_score(
            _count_pattern_hits(lowered, EXCITEMENT_PATTERNS) * 1.8
            + exclamation_count * 1.5
            + _deterministic_jitter(text, "excitement")
        )
        humor = _clamp_score(
            _count_pattern_hits(lowered, HUMOR_PATTERNS) * 2.2
            + _deterministic_jitter(text, "humor")
        )
        suspense = _clamp_score(
            _count_pattern_hits(lowered, SUSPENSE_PATTERNS) * 2.0
            + question_count * 1.2
            + _deterministic_jitter(text, "suspense")
        )
        educational = _clamp_score(
            _count_pattern_hits(lowered, EDUCATIONAL_PATTERNS) * 2.0
            + (1.0 if word_count >= 12 else 0.0)
            + _deterministic_jitter(text, "educational")
        )
        context_dependency = _clamp_score(
            _count_pattern_hits(lowered, CONTEXT_PATTERNS) * 2.5
            + (1.5 if word_count <= 4 else 0.0)
            + _deterministic_jitter(text, "context")
        )
        standalone = _clamp_score(10.0 - context_dependency * 0.85)

        emotion = self._pick_emotion(
            excitement=excitement,
            humor=humor,
            suspense=suspense,
            educational=educational,
            text=text,
        )
        clip_candidate = self._is_clip_candidate(
            excitement=excitement,
            humor=humor,
            suspense=suspense,
            standalone=standalone,
        )
        reason = self._build_reason(
            clip_candidate=clip_candidate,
            emotion=emotion,
            excitement=excitement,
            humor=humor,
            suspense=suspense,
            standalone=standalone,
        )

        return SegmentAnalysis(
            segment_id=segment.id,
            start=segment.start,
            end=segment.end,
            text=text,
            emotion=emotion,
            excitement_score=excitement,
            humor_score=humor,
            suspense_score=suspense,
            educational_score=educational,
            standalone_score=standalone,
            context_dependency_score=context_dependency,
            clip_candidate=clip_candidate,
            reason=reason,
        )

    def _pick_emotion(
        self,
        *,
        excitement: float,
        humor: float,
        suspense: float,
        educational: float,
        text: str,
    ) -> str:
        scores = {
            "excited": excitement,
            "humorous": humor,
            "tense": suspense,
            "informative": educational,
            "surprised": text.count("!") + text.count("?"),
            "frustrated": 1.0 if "ugh" in text.lower() or "damn" in text.lower() else 0.0,
        }
        best_emotion = max(scores, key=scores.get)
        if scores[best_emotion] < 2.5:
            index = int(_deterministic_jitter(text, "emotion") * len(EMOTIONS)) % len(EMOTIONS)
            return EMOTIONS[index]
        return best_emotion

    def _is_clip_candidate(
        self,
        *,
        excitement: float,
        humor: float,
        suspense: float,
        standalone: float,
    ) -> bool:
        peak = max(excitement, humor, suspense)
        average = (excitement + humor + suspense) / 3.0
        return standalone >= 5.0 and (peak >= 6.0 or average >= 5.5)

    def _build_reason(
        self,
        *,
        clip_candidate: bool,
        emotion: str,
        excitement: float,
        humor: float,
        suspense: float,
        standalone: float,
    ) -> str:
        if clip_candidate:
            drivers = []
            if excitement >= 6.0:
                drivers.append(f"excitement {excitement:.1f}/10")
            if humor >= 6.0:
                drivers.append(f"humor {humor:.1f}/10")
            if suspense >= 6.0:
                drivers.append(f"suspense {suspense:.1f}/10")
            driver_text = ", ".join(drivers) if drivers else "balanced engagement scores"
            return (
                "Heuristic fallback candidate: "
                f"{emotion} tone with {driver_text} and standalone {standalone:.1f}/10."
            )
        return (
            "Heuristic fallback: segment did not meet clip thresholds "
            f"(standalone {standalone:.1f}/10, peak engagement below 6.0)."
        )
