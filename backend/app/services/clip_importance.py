from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings
from app.models.project import (
    ClipCandidate,
    ImportanceBreakdown,
    RejectedClipCandidate,
    SegmentAnalysis,
    VisualEvidence,
    VisualSignalScores,
)

FILLER_PATTERNS = (
    "okay",
    "yeah",
    "uh",
    "um",
    "like",
    "you know",
    "i mean",
    "so yeah",
    "anyway",
)
CONTROVERSY_PATTERNS = (
    "wrong",
    "controversial",
    "unpopular",
    "hot take",
    "disagree",
    "overrated",
    "underrated",
)
PROFANITY_PATTERNS = ("damn", "hell", "shit", "fuck", "ass")
QUESTION_STARTERS = ("why", "what", "how", "who", "when", "where", "did", "is", "are", "can")


def _clamp(value: float, lower: float = 0.0, upper: float = 10.0) -> float:
    return max(lower, min(upper, value))


def _round_dim(value: float) -> float:
    return round(_clamp(value), 1)


def _word_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", text.lower()) if len(token) > 2}


def _peak_engagement(segments: list[SegmentAnalysis]) -> float:
    return max(
        max(segment.excitement_score for segment in segments),
        max(segment.humor_score for segment in segments),
        max(segment.suspense_score for segment in segments),
        max(segment.educational_score for segment in segments),
    )


def _average_engagement(segments: list[SegmentAnalysis]) -> float:
    return sum(
        (
            segment.excitement_score
            + segment.humor_score
            + segment.suspense_score
            + segment.educational_score
        )
        / 4.0
        for segment in segments
    ) / len(segments)


def _score_hook(segments: list[SegmentAnalysis], *, hook_score: float) -> float:
    first = segments[0]
    text = first.text.strip().lower()
    words = re.findall(r"\b\w+\b", text)
    score = hook_score * 0.55
    if text.endswith("?"):
        score += 1.8
    if words and words[0] in QUESTION_STARTERS:
        score += 1.2
    if any(pattern in text for pattern in ("wait", "no way", "insane", "crazy", "hold on")):
        score += 1.5
    if "!" in first.text:
        score += 0.8
    if len(words) >= 6 and first.excitement_score >= 5.0:
        score += 0.6
    return _round_dim(score)


def _score_emotion(segments: list[SegmentAnalysis], *, primary_emotion: str) -> float:
    peak_excitement = max(segment.excitement_score for segment in segments)
    peak_humor = max(segment.humor_score for segment in segments)
    peak_suspense = max(segment.suspense_score for segment in segments)
    emotion_boost = {
        "excited": 1.2,
        "humorous": 1.0,
        "tense": 1.1,
        "surprised": 1.3,
        "frustrated": 0.8,
        "informative": 0.5,
        "neutral": 0.0,
    }.get(primary_emotion, 0.0)
    score = max(peak_excitement, peak_humor, peak_suspense) * 0.65 + emotion_boost
    if peak_humor >= 6.0 and peak_excitement >= 5.0:
        score += 0.8
    return _round_dim(score)


def _score_story_value(segments: list[SegmentAnalysis], *, hook_score: float, payoff_score: float) -> float:
    if len(segments) == 1:
        return _round_dim((hook_score + payoff_score) / 2.0 * 0.6)

    middle = segments[1:-1]
    middle_peak = _peak_engagement(middle) if middle else 0.0
    setup = hook_score * 0.25
    escalation = middle_peak * 0.35
    payoff = payoff_score * 0.4
    arc_bonus = 0.0
    if hook_score >= 4.0 and payoff_score >= 3.5:
        arc_bonus += 1.5
    if middle_peak >= hook_score * 0.8 and payoff_score >= middle_peak * 0.7:
        arc_bonus += 1.0
    return _round_dim(setup + escalation + payoff + arc_bonus)


def _score_information_value(segments: list[SegmentAnalysis]) -> float:
    educational_peak = max(segment.educational_score for segment in segments)
    educational_avg = sum(segment.educational_score for segment in segments) / len(segments)
    text = " ".join(segment.text for segment in segments).lower()
    score = educational_peak * 0.55 + educational_avg * 0.25
    if any(pattern in text for pattern in ("because", "how to", "tip", "learn", "means", "reason")):
        score += 1.2
    if len(_word_tokens(text)) >= 18:
        score += 0.6
    return _round_dim(score)


def _score_retention(
    segments: list[SegmentAnalysis],
    *,
    payoff_score: float,
    context_dependency_score: float,
) -> float:
    suspense_avg = sum(segment.suspense_score for segment in segments) / len(segments)
    score = payoff_score * 0.35 + suspense_avg * 0.35 + (10.0 - context_dependency_score) * 0.15
    if segments[-1].text.strip().endswith(("!", "?", "...")):
        score += 0.8
    if len(segments) >= 3:
        late = segments[-2:]
        if _peak_engagement(late) >= _peak_engagement(segments[:-2]):
            score += 1.0
    return _round_dim(score)


def _score_shareability(segments: list[SegmentAnalysis], *, primary_emotion: str) -> float:
    peak_humor = max(segment.humor_score for segment in segments)
    peak_excitement = max(segment.excitement_score for segment in segments)
    text = " ".join(segment.text for segment in segments).lower()
    score = peak_humor * 0.35 + peak_excitement * 0.25
    if any(pattern in text for pattern in CONTROVERSY_PATTERNS):
        score += 1.5
    if primary_emotion in {"humorous", "surprised", "excited", "tense"}:
        score += 0.8
    if "!" in text:
        score += 0.4
    return _round_dim(score)


def _score_standalone_quality(
    *,
    standalone_score: float,
    context_dependency_score: float,
    hook_score: float,
    payoff_score: float,
) -> float:
    score = standalone_score * 0.65 + (10.0 - context_dependency_score) * 0.2
    if hook_score >= 3.0 and payoff_score >= 2.5:
        score += 1.0
    if context_dependency_score >= 7.0:
        score -= 2.0
    return _round_dim(score)


def _score_monetization_potential(
    segments: list[SegmentAnalysis],
    *,
    standalone_score: float,
    hook_score: float,
    information_value: float,
    context_dependency_score: float,
) -> float:
    text = " ".join(segment.text for segment in segments).lower()
    score = standalone_score * 0.3 + information_value * 0.25 + hook_score * 0.15
    score += (10.0 - context_dependency_score) * 0.15
    if any(pattern in text for pattern in PROFANITY_PATTERNS):
        score -= 2.5
    if len(_word_tokens(text)) >= 10:
        score += 0.8
    if segments[0].text.strip():
        score += 0.5
    return _round_dim(score)


DIMENSION_WEIGHTS: dict[str, float] = {
    "hook": 0.12,
    "emotion": 0.10,
    "story_value": 0.14,
    "information_value": 0.12,
    "retention": 0.12,
    "shareability": 0.10,
    "standalone_quality": 0.18,
    "monetization_potential": 0.12,
}


def compute_importance_breakdown(
    segments: list[SegmentAnalysis],
    *,
    hook_score: float,
    payoff_score: float,
    standalone_score: float,
    context_dependency_score: float,
    primary_emotion: str,
) -> ImportanceBreakdown:
    information_value = _score_information_value(segments)
    breakdown = ImportanceBreakdown(
        hook=_score_hook(segments, hook_score=hook_score),
        emotion=_score_emotion(segments, primary_emotion=primary_emotion),
        story_value=_score_story_value(segments, hook_score=hook_score, payoff_score=payoff_score),
        information_value=information_value,
        retention=_score_retention(
            segments,
            payoff_score=payoff_score,
            context_dependency_score=context_dependency_score,
        ),
        shareability=_score_shareability(segments, primary_emotion=primary_emotion),
        standalone_quality=_score_standalone_quality(
            standalone_score=standalone_score,
            context_dependency_score=context_dependency_score,
            hook_score=hook_score,
            payoff_score=payoff_score,
        ),
        monetization_potential=_score_monetization_potential(
            segments,
            standalone_score=standalone_score,
            hook_score=hook_score,
            information_value=information_value,
            context_dependency_score=context_dependency_score,
        ),
    )
    return breakdown


def importance_total_score(breakdown: ImportanceBreakdown) -> float:
    weighted = sum(getattr(breakdown, key) * weight for key, weight in DIMENSION_WEIGHTS.items())
    return round(_clamp(weighted * 10.0, 0.0, 100.0), 1)


def importance_breakdown_to_score_dict(breakdown: ImportanceBreakdown) -> dict[str, float]:
    return {
        "importance_hook": breakdown.hook,
        "importance_emotion": breakdown.emotion,
        "importance_story_value": breakdown.story_value,
        "importance_information_value": breakdown.information_value,
        "importance_retention": breakdown.retention,
        "importance_shareability": breakdown.shareability,
        "importance_standalone_quality": breakdown.standalone_quality,
        "importance_monetization_potential": breakdown.monetization_potential,
    }


@dataclass(frozen=True)
class WeaknessAssessment:
    reject: bool
    reason: str | None


def assess_candidate_weakness(
    segments: list[SegmentAnalysis],
    *,
    hook_score: float,
    payoff_score: float,
    standalone_score: float,
    context_dependency_score: float,
    importance: ImportanceBreakdown,
    total_score: float,
    min_score: float,
) -> WeaknessAssessment:
    peak = _peak_engagement(segments)
    average = _average_engagement(segments)
    text = " ".join(segment.text for segment in segments).lower().strip()
    words = re.findall(r"\b\w+\b", text)

    if total_score < min_score:
        return WeaknessAssessment(True, f"Score {total_score:.1f} below minimum {min_score:.1f}.")

    if standalone_score < 4.0 and context_dependency_score >= 5.5:
        return WeaknessAssessment(True, "Too context-dependent to stand alone.")

    if hook_score < 2.5 and payoff_score < 2.5 and peak < 5.0:
        return WeaknessAssessment(True, "Ordinary conversation with no hook or payoff.")

    if peak < 4.5 and average < 3.5:
        return WeaknessAssessment(True, "Low-energy segment with weak engagement.")

    if payoff_score < 2.0 and importance.story_value < 4.0 and importance.information_value < 4.0:
        return WeaknessAssessment(True, "Weak setup with no payoff or information value.")

    filler_hits = sum(1 for pattern in FILLER_PATTERNS if pattern in text)
    if len(words) <= 8 and filler_hits >= 2 and peak < 5.5:
        return WeaknessAssessment(True, "Generic filler with little postable value.")

    if importance.standalone_quality < 4.0 and context_dependency_score >= 6.0:
        return WeaknessAssessment(True, "Requires too much outside context.")

    if importance.hook < 3.0 and importance.retention < 3.5 and importance.shareability < 3.5:
        return WeaknessAssessment(
            True,
            "No compelling hook, retention driver, or shareability signal.",
        )

    return WeaknessAssessment(False, None)


def build_selection_reasons(
    importance: ImportanceBreakdown,
    *,
    hook_score: float,
    payoff_score: float,
    primary_emotion: str,
) -> list[str]:
    reasons: list[str] = []

    if importance.hook >= 6.5:
        reasons.append("Strong curiosity hook in the opening")
    elif importance.hook >= 5.0 and hook_score >= 4.0:
        reasons.append("Solid opening hook that pulls viewers in")

    if importance.story_value >= 6.5 and payoff_score >= 4.0:
        reasons.append("Complete mini-arc with setup and payoff")
    elif importance.story_value >= 5.5:
        reasons.append("Clear narrative progression within the clip")

    if importance.emotion >= 6.5:
        reasons.append(f"High emotional reaction ({primary_emotion})")
    elif importance.emotion >= 5.0:
        reasons.append(f"Engaging {primary_emotion} tone")

    if importance.information_value >= 6.0:
        reasons.append("Useful standalone explanation with strong information density")
    elif importance.information_value >= 5.0:
        reasons.append("Clear insight or educational value")

    if importance.shareability >= 6.0 and importance.emotion >= 5.0:
        reasons.append("High shareability from humor or surprise")
    elif importance.shareability >= 5.5:
        reasons.append("Relatable or discussion-worthy moment")

    if importance.retention >= 6.0:
        reasons.append("Strong reason to keep watching through the end")

    if importance.standalone_quality >= 6.5:
        reasons.append("Understandable without outside context")

    if importance.monetization_potential >= 6.0:
        reasons.append("Broad audience appeal with a clear topic premise")

    if not reasons:
        top_dims = sorted(
            [
                ("hook", importance.hook),
                ("emotion", importance.emotion),
                ("story", importance.story_value),
                ("information", importance.information_value),
                ("retention", importance.retention),
                ("shareability", importance.shareability),
                ("standalone", importance.standalone_quality),
            ],
            key=lambda item: item[1],
            reverse=True,
        )[:2]
        label_map = {
            "hook": "opening strength",
            "emotion": "emotional pull",
            "story": "story value",
            "information": "information value",
            "retention": "retention potential",
            "shareability": "shareability",
            "standalone": "standalone clarity",
        }
        reasons.append(
            "Selected for "
            + " and ".join(f"strong {label_map[key]}" for key, _ in top_dims)
        )

    return reasons[:4]


def build_selection_warnings(
    segments: list[SegmentAnalysis],
    *,
    hook_score: float,
    context_dependency_score: float,
    importance: ImportanceBreakdown,
    confidence: float,
) -> list[str]:
    warnings: list[str] = []
    if confidence < 0.55:
        warnings.append("Lower selection confidence from mixed segment signals")
    if context_dependency_score >= 5.5 or importance.standalone_quality < 5.0:
        warnings.append("May require visual or prior context")
    if hook_score < 3.5 and importance.hook < 5.0:
        warnings.append("Slower opening before the strongest moment")
    if segments[0].standalone_score < 4.5:
        warnings.append("Opening segment has weaker standalone clarity")
    return warnings


def build_human_reason(
    selection_reasons: list[str],
    *,
    total_score: float,
    importance: ImportanceBreakdown,
) -> str:
    lead = selection_reasons[0] if selection_reasons else "Balanced importance across clip dimensions"
    return (
        f"{lead}. Overall importance {total_score:.1f}/100 "
        f"(hook {importance.hook:.1f}, story {importance.story_value:.1f}, "
        f"standalone {importance.standalone_quality:.1f})."
    )


def transcript_overlap_ratio(first: ClipCandidate, second: ClipCandidate) -> float:
    first_tokens = _word_tokens(first.transcript_text)
    second_tokens = _word_tokens(second.transcript_text)
    if not first_tokens or not second_tokens:
        return 0.0
    overlap = len(first_tokens & second_tokens)
    smaller = min(len(first_tokens), len(second_tokens))
    return overlap / smaller if smaller else 0.0


def _topic_bucket(candidate: ClipCandidate) -> str:
    tokens = sorted(_word_tokens(candidate.transcript_text))
    if not tokens:
        return candidate.primary_emotion
    return " ".join(tokens[:5])


def _diversity_penalty(candidate: ClipCandidate, selected: list[ClipCandidate]) -> float:
    penalty = 0.0
    bucket = _topic_bucket(candidate)
    for existing in selected:
        if _topic_bucket(existing) == bucket:
            penalty += 6.0
        if existing.primary_emotion == candidate.primary_emotion:
            penalty += 3.0
        if transcript_overlap_ratio(candidate, existing) >= 0.45:
            penalty += 8.0
        elif transcript_overlap_ratio(candidate, existing) >= 0.30:
            penalty += 4.0
    return penalty


def _candidate_overlap_ratio(first: ClipCandidate, second: ClipCandidate) -> float:
    overlap_start = max(first.start, second.start)
    overlap_end = min(first.end, second.end)
    if overlap_end <= overlap_start:
        return 0.0
    overlap = overlap_end - overlap_start
    shorter = min(first.duration, second.duration)
    return overlap / shorter if shorter > 0 else 0.0


def _duration_preference_bonus(candidate: ClipCandidate) -> float:
    preferred_max = settings.clip_selection_preferred_target_max_seconds
    preferred_min = settings.clip_selection_preferred_min_duration_seconds
    if preferred_min <= candidate.duration <= preferred_max:
        return 8.0
    if candidate.duration < preferred_min:
        return -6.0
    if candidate.duration <= preferred_max + 15.0:
        return 2.0
    return -2.0


def _effective_rank_score(candidate: ClipCandidate, selected: list[ClipCandidate]) -> float:
    return candidate.score + _duration_preference_bonus(candidate) - _diversity_penalty(candidate, selected)


def global_importance_selection(
    candidates: list[ClipCandidate],
    *,
    max_count: int,
    quality_threshold: float,
    source_duration: float,
) -> tuple[list[ClipCandidate], list[RejectedClipCandidate]]:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.duration + 0.01 >= settings.clip_selection_min_duration_seconds
        or source_duration + 0.05 < settings.clip_selection_min_duration_seconds
    ]
    eligible.sort(
        key=lambda candidate: (
            candidate.score + _duration_preference_bonus(candidate),
            candidate.confidence,
            -candidate.start,
        ),
        reverse=True,
    )

    selected: list[ClipCandidate] = []
    rejected: list[RejectedClipCandidate] = []

    for candidate in eligible:
        if candidate.score < quality_threshold:
            rejected.append(
                RejectedClipCandidate(
                    clip_id=candidate.clip_id,
                    start=candidate.start,
                    end=candidate.end,
                    duration=candidate.duration,
                    score=candidate.score,
                    score_breakdown=candidate.score_breakdown,
                    importance_breakdown=candidate.importance_breakdown,
                    reason=candidate.reason,
                    rejection_reason=(
                        f"Below quality threshold ({candidate.score:.1f} < {quality_threshold:.1f})."
                    ),
                )
            )
            continue

        if len(selected) >= max_count:
            rejected.append(
                RejectedClipCandidate(
                    clip_id=candidate.clip_id,
                    start=candidate.start,
                    end=candidate.end,
                    duration=candidate.duration,
                    score=candidate.score,
                    score_breakdown=candidate.score_breakdown,
                    importance_breakdown=candidate.importance_breakdown,
                    reason=candidate.reason,
                    rejection_reason="Exceeded final clip count limit.",
                )
            )
            continue

        overlap_conflict = [
            existing
            for existing in selected
            if _candidate_overlap_ratio(candidate, existing) >= 0.55
        ]
        if overlap_conflict:
            stronger = max(existing.score for existing in overlap_conflict)
            if candidate.score <= stronger + 4.0:
                rejected.append(
                    RejectedClipCandidate(
                        clip_id=candidate.clip_id,
                        start=candidate.start,
                        end=candidate.end,
                        duration=candidate.duration,
                        score=candidate.score,
                        score_breakdown=candidate.score_breakdown,
                        importance_breakdown=candidate.importance_breakdown,
                        reason=candidate.reason,
                        rejection_reason="Overlaps a stronger selected clip.",
                    )
                )
                continue

        similar = [
            existing
            for existing in selected
            if transcript_overlap_ratio(candidate, existing) >= 0.42
            or (
                existing.primary_emotion == candidate.primary_emotion
                and _candidate_overlap_ratio(candidate, existing) >= 0.25
            )
        ]
        if similar and candidate.score <= max(existing.score for existing in similar) + 2.0:
            rejected.append(
                RejectedClipCandidate(
                    clip_id=candidate.clip_id,
                    start=candidate.start,
                    end=candidate.end,
                    duration=candidate.duration,
                    score=candidate.score,
                    score_breakdown=candidate.score_breakdown,
                    importance_breakdown=candidate.importance_breakdown,
                    reason=candidate.reason,
                    rejection_reason="Too similar to a stronger selected clip.",
                )
            )
            continue

        diversity_adjusted = _effective_rank_score(candidate, selected)
        if selected and diversity_adjusted < quality_threshold - 5.0:
            rejected.append(
                RejectedClipCandidate(
                    clip_id=candidate.clip_id,
                    start=candidate.start,
                    end=candidate.end,
                    duration=candidate.duration,
                    score=candidate.score,
                    score_breakdown=candidate.score_breakdown,
                    importance_breakdown=candidate.importance_breakdown,
                    reason=candidate.reason,
                    rejection_reason="Redundant topic or emotion versus stronger picks.",
                )
            )
            continue

        selected.append(candidate)

    selected.sort(key=lambda candidate: candidate.start)
    return selected, rejected


def empty_visual_evidence() -> VisualEvidence:
    return VisualEvidence()
