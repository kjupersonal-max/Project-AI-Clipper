from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.models.project import (
    ClipCandidate,
    VisualAnalysisDocument,
    VisualEvidence,
    VisualWindow,
)
from app.services.visual_analysis import windows_overlapping_range


@dataclass(frozen=True)
class VisualScoringResult:
    transcript_only_score: float
    visual_contribution: float
    selection_rank_score: float
    combined_score: float
    evidence: VisualEvidence
    reasons: list[str]
    warnings: list[str]
    blocked_reason: str | None = None
    would_change_ranking: bool = False


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _dedupe_events(events: list[str]) -> list[str]:
    unique: list[str] = []
    for event in events:
        if event not in unique:
            unique.append(event)
    return unique


def _find_payoff_timestamp(candidate: ClipCandidate) -> float:
    importance = candidate.importance_breakdown
    if importance is not None and importance.story_value >= importance.hook:
        return round(candidate.end - min(3.0, candidate.duration * 0.25), 3)
    return round(candidate.start + min(4.0, candidate.duration * 0.35), 3)


def _alignment_targets(candidate: ClipCandidate) -> list[tuple[float, str]]:
    targets: list[tuple[float, str]] = []
    payoff_time = _find_payoff_timestamp(candidate)
    targets.append((payoff_time, "payoff"))
    targets.append((candidate.start, "hook"))
    if candidate.duration >= 18.0:
        mid = candidate.start + candidate.duration * 0.55
        targets.append((round(mid, 3), "escalation"))
    reaction_time = round(candidate.end - min(2.0, candidate.duration * 0.15), 3)
    if reaction_time > candidate.start + 2.0:
        targets.append((reaction_time, "reaction"))
    return targets


def _best_aligned_window(
    windows: list[VisualWindow],
    targets: list[tuple[float, str]],
) -> tuple[VisualWindow | None, str | None, float | None, float]:
    best_window: VisualWindow | None = None
    best_event: str | None = None
    best_timestamp: float | None = None
    best_distance = float("inf")

    for timestamp, event in targets:
        for window in windows:
            if window.start - 0.5 <= timestamp <= window.end + 0.5:
                distance = abs((window.peak_motion_timestamp or window.start) - timestamp)
                if distance < best_distance:
                    best_distance = distance
                    best_window = window
                    best_event = event
                    best_timestamp = timestamp

    for timestamp, event in targets:
        for window in windows:
            anchor = window.peak_motion_timestamp or window.start
            distance = abs(anchor - timestamp)
            limit = (
                settings.visual_analysis_payoff_alignment_window_seconds
                if event == "payoff"
                else settings.visual_analysis_alignment_window_seconds
            )
            if distance <= limit and distance < best_distance:
                best_distance = distance
                best_window = window
                best_event = event
                best_timestamp = timestamp

    return best_window, best_event, best_timestamp, best_distance


def _is_gameplay_baseline_motion(windows: list[VisualWindow]) -> bool:
    if len(windows) < 4:
        return False
    active = [window for window in windows if window.activity_score >= 4.0]
    if len(active) < len(windows) * 0.6:
        return False
    peaks = [window.motion_score for window in windows]
    if max(peaks) - min(peaks) <= 2.0:
        return True
    return False


def compute_visual_scoring_result(
    candidate: ClipCandidate,
    document: VisualAnalysisDocument,
    *,
    quality_threshold: float,
    apply_ranking: bool,
) -> VisualScoringResult:
    windows = windows_overlapping_range(document, candidate.start, candidate.end)
    evidence = VisualEvidence(provider=document.provider, model=document.model)
    transcript_only_score = candidate.score
    reasons: list[str] = []
    warnings: list[str] = []

    if not windows:
        return VisualScoringResult(
            transcript_only_score=transcript_only_score,
            visual_contribution=0.0,
            selection_rank_score=transcript_only_score,
            combined_score=transcript_only_score,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
            blocked_reason="No visual windows overlap clip range.",
        )

    aligned_window, aligned_event, aligned_timestamp, alignment_distance = _best_aligned_window(
        windows,
        _alignment_targets(candidate),
    )

    motion_peak = max(window.motion_score for window in windows)
    scene_peak = max(window.scene_change_score for window in windows)
    activity_peak = max(window.activity_score for window in windows)
    measured: list[str] = []

    if aligned_window is not None and aligned_window.motion_score >= 5.0:
        if "motion_spike" in aligned_window.events or aligned_window.motion_score >= 6.0:
            measured.append("motion_spike")
    if aligned_window is not None and "camera_cut" in aligned_window.events:
        measured.append("camera_cut")
    if activity_peak >= 5.0 and aligned_window is not None:
        measured.append("visual_activity")
    measured = _dedupe_events(measured)

    evidence.signals.motion_spike = round(motion_peak, 2) if motion_peak >= 4.0 else None
    evidence.signals.scene_change = round(scene_peak, 2) if scene_peak >= 4.0 else None
    evidence.signals.physical_action = (
        round(min(10.0, motion_peak * 0.7 + activity_peak * 0.2), 2)
        if motion_peak >= 4.0
        else None
    )
    evidence.measured_signals = measured

    if aligned_window is None or aligned_event is None or aligned_timestamp is None:
        evidence.blocked_reason = "No visual spike aligned with a transcript hook, payoff, or reaction."
        return VisualScoringResult(
            transcript_only_score=transcript_only_score,
            visual_contribution=0.0,
            selection_rank_score=transcript_only_score,
            combined_score=transcript_only_score,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
            blocked_reason=evidence.blocked_reason,
        )

    evidence.aligned_timestamp = aligned_window.peak_motion_timestamp or aligned_window.start
    evidence.aligned_transcript_event = aligned_event
    evidence.alignment_confidence = round(
        _clamp(1.0 - (alignment_distance / max(settings.visual_analysis_alignment_window_seconds, 0.1)), 0.0, 1.0),
        2,
    )
    evidence.alignment_reason = (
        f"Motion spike aligned within {alignment_distance:.1f}s of the spoken {aligned_event}."
    )

    if _is_gameplay_baseline_motion(windows):
        evidence.blocked_reason = "Constant gameplay motion treated as baseline activity."
        warnings.append("Visually active, but motion appears continuous rather than a distinct event.")
        return VisualScoringResult(
            transcript_only_score=transcript_only_score,
            visual_contribution=0.0,
            selection_rank_score=transcript_only_score,
            combined_score=transcript_only_score,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
            blocked_reason=evidence.blocked_reason,
        )

    if measured == ["camera_cut"] or (len(measured) == 1 and measured[0] == "camera_cut"):
        evidence.blocked_reason = "Camera cut alone is insufficient without aligned payoff motion."
        warnings.append("Camera cut detected without strong aligned transcript payoff.")
        return VisualScoringResult(
            transcript_only_score=transcript_only_score,
            visual_contribution=0.0,
            selection_rank_score=transcript_only_score,
            combined_score=transcript_only_score,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
            blocked_reason=evidence.blocked_reason,
        )

    if candidate.standalone_score < 4.0 and candidate.payoff_score < 4.0:
        evidence.blocked_reason = "Limited transcript context prevents a meaningful visual boost."
        warnings.append("Visually active, but transcript context is limited.")
        return VisualScoringResult(
            transcript_only_score=transcript_only_score,
            visual_contribution=0.0,
            selection_rank_score=transcript_only_score,
            combined_score=transcript_only_score,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
            blocked_reason=evidence.blocked_reason,
        )

    raw_boost = 0.0
    aligned_motion = aligned_window.motion_score
    if aligned_event == "payoff" and candidate.payoff_score >= 4.0 and aligned_motion >= 6.0:
        raw_boost += 1.2 + min(0.8, (aligned_motion - 6.0) * 0.2)
        reasons.append("Strong spoken payoff aligned with a high-motion visual reaction.")
    elif aligned_event in {"reaction", "escalation"} and aligned_motion >= 6.5:
        raw_boost += 0.8
        reasons.append(f"Visual activity aligned with the clip {aligned_event}.")
    elif aligned_motion >= 7.5 and transcript_only_score >= quality_threshold + 4.0:
        raw_boost += 0.6
        reasons.append("Aligned visual spike supports an already strong transcript moment.")

    raw_boost *= 0.5 + evidence.alignment_confidence * 0.5

    exceptional = (
        aligned_motion >= settings.visual_analysis_exceptional_motion_threshold
        and candidate.payoff_score >= 5.0
        and candidate.standalone_score >= 5.0
        and transcript_only_score >= settings.visual_analysis_min_transcript_score_for_boost
        and aligned_event == "payoff"
        and alignment_distance <= settings.visual_analysis_payoff_alignment_window_seconds
    )
    max_boost = (
        settings.visual_analysis_exceptional_visual_boost
        if exceptional
        else settings.visual_analysis_max_visual_boost
    )
    visual_contribution = round(_clamp(raw_boost, 0.0, max_boost), 2)
    evidence.visual_contribution = visual_contribution

    if transcript_only_score + 0.05 < quality_threshold:
        blocked = (
            "Visual boost blocked because transcript score is below the quality threshold."
        )
        evidence.blocked_reason = blocked
        return VisualScoringResult(
            transcript_only_score=transcript_only_score,
            visual_contribution=visual_contribution,
            selection_rank_score=transcript_only_score,
            combined_score=transcript_only_score,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
            blocked_reason=blocked,
            would_change_ranking=visual_contribution > 0.0,
        )

    tie_breaker = 0.0
    if apply_ranking and visual_contribution > 0.0:
        tie_breaker = min(
            visual_contribution,
            settings.visual_analysis_tie_breaker_max_boost,
        )

    selection_rank_score = round(transcript_only_score + tie_breaker, 1)
    combined_score = round(transcript_only_score + visual_contribution, 1)

    return VisualScoringResult(
        transcript_only_score=transcript_only_score,
        visual_contribution=visual_contribution,
        selection_rank_score=selection_rank_score,
        combined_score=combined_score,
        evidence=evidence,
        reasons=reasons,
        warnings=warnings,
        would_change_ranking=tie_breaker > 0.0,
    )


def apply_visual_scoring(
    candidates: list[ClipCandidate],
    document: VisualAnalysisDocument | None,
    *,
    quality_threshold: float | None = None,
) -> list[ClipCandidate]:
    if document is None or not settings.visual_analysis_enabled:
        return candidates

    mode = settings.visual_analysis_ranking_mode.lower()
    if mode == "disabled":
        return candidates

    threshold = quality_threshold or settings.clip_selection_quality_threshold
    apply_ranking = mode == "conservative"

    updated: list[ClipCandidate] = []
    for candidate in candidates:
        result = compute_visual_scoring_result(
            candidate,
            document,
            quality_threshold=threshold,
            apply_ranking=apply_ranking,
        )
        score_breakdown = dict(candidate.score_breakdown)
        score_breakdown["transcript_only_score"] = result.transcript_only_score
        score_breakdown["visual_contribution"] = result.visual_contribution
        score_breakdown["combined_score"] = result.combined_score
        score_breakdown["selection_rank_score"] = result.selection_rank_score
        if mode == "shadow":
            score_breakdown["visual_shadow_mode"] = 1.0
            if result.would_change_ranking:
                score_breakdown["visual_would_change_ranking"] = 1.0

        selection_reasons = list(candidate.selection_reasons)
        selection_reasons.extend(reason for reason in result.reasons if reason not in selection_reasons)
        merged_warnings = list(candidate.warnings)
        merged_warnings.extend(warning for warning in result.warnings if warning not in merged_warnings)
        if result.blocked_reason and mode != "shadow":
            note = result.blocked_reason
            if note not in merged_warnings:
                merged_warnings.append(note)

        updated.append(
            candidate.model_copy(
                update={
                    "score": result.transcript_only_score,
                    "visual_evidence": result.evidence,
                    "score_breakdown": score_breakdown,
                    "selection_reasons": selection_reasons[:5],
                    "warnings": merged_warnings,
                }
            )
        )
    return updated


def visual_ranking_score(candidate: ClipCandidate) -> float:
    breakdown = candidate.score_breakdown or {}
    if "selection_rank_score" in breakdown:
        return float(breakdown["selection_rank_score"])
    return candidate.score


def should_apply_visual_boundaries() -> bool:
    if not settings.visual_analysis_enabled:
        return False
    return settings.visual_analysis_ranking_mode.lower() == "conservative"
