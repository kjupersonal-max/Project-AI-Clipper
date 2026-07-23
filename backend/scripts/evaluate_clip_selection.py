#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.clip_selection import (
    ClipCandidatesNotFoundError,
    load_project_clip_candidates,
    select_project_clips,
)
from app.services.visual_analysis import analyze_project_visuals, load_project_visual_analysis


PHASE5_BASELINE = [
    {"start": 13.28, "end": 33.74},
    {"start": 85.54, "end": 123.98},
    {"start": 740.90, "end": 761.78},
]


def _format_candidate(candidate: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    importance = candidate.get("importance_breakdown") or {}
    score_breakdown = candidate.get("score_breakdown") or {}
    visual = candidate.get("visual_evidence") or {}
    return {
        "rank": rank,
        "clip_id": candidate.get("clip_id"),
        "start": candidate.get("start"),
        "end": candidate.get("end"),
        "duration": candidate.get("duration"),
        "score": candidate.get("score"),
        "transcript_only_score": score_breakdown.get("transcript_only_score", candidate.get("score")),
        "visual_contribution": score_breakdown.get("visual_contribution", 0),
        "selection_rank_score": score_breakdown.get("selection_rank_score"),
        "combined_score": score_breakdown.get("combined_score", candidate.get("score")),
        "primary_emotion": candidate.get("primary_emotion"),
        "selection_reasons": candidate.get("selection_reasons", []),
        "warnings": candidate.get("warnings", []),
        "reason": candidate.get("reason"),
        "score_breakdown": score_breakdown,
        "importance_breakdown": importance,
        "visual_evidence": visual,
        "visual_reasons": [
            reason
            for reason in candidate.get("selection_reasons", [])
            if any(token in reason.lower() for token in ("visual", "motion", "aligned", "camera", "activity"))
        ],
        "boundary_visual_warnings": [
            warning
            for warning in candidate.get("warnings", [])
            if any(token in warning.lower() for token in ("visual", "lead-in", "activity", "blocked"))
        ],
        "transcript_preview": (candidate.get("transcript_text") or "")[:160],
    }


def _clip_signature(candidate: dict[str, Any]) -> tuple[float, float]:
    return (round(float(candidate.get("start", 0)), 2), round(float(candidate.get("end", 0)), 2))


def _compare_to_baseline(selected: list[dict[str, Any]], baseline: list[dict[str, float]]) -> dict[str, Any]:
    matched = []
    missing = []
    unexpected = []
    timestamp_changes = []

    selected_sigs = [_clip_signature(item) for item in selected]
    baseline_sigs = [_clip_signature(item) for item in baseline]

    for index, target in enumerate(baseline):
        target_sig = _clip_signature(target)
        match = next((item for item in selected if _clip_signature(item) == target_sig), None)
        if match is None:
            closest = next(
                (
                    item
                    for item in selected
                    if abs(item["start"] - target["start"]) < 20
                    or abs(item["end"] - target["end"]) < 20
                ),
                None,
            )
            if closest is None:
                missing.append({"baseline_rank": index + 1, **target})
            else:
                timestamp_changes.append(
                    {
                        "baseline_rank": index + 1,
                        "baseline": target_sig,
                        "current": _clip_signature(closest),
                        "clip_id": closest.get("clip_id"),
                    }
                )
        else:
            matched.append({"baseline_rank": index + 1, "clip_id": match.get("clip_id"), **target})

    for item in selected:
        if _clip_signature(item) not in baseline_sigs:
            unexpected.append(item)

    return {
        "matched": matched,
        "missing": missing,
        "unexpected": unexpected,
        "timestamp_changes": timestamp_changes,
        "matches_phase5_baseline": not missing and not timestamp_changes and not unexpected,
    }


def _run_mode(project_id: str, *, mode: str, rerun: bool, visual_force: bool) -> dict[str, Any]:
    original_mode = settings.visual_analysis_ranking_mode
    original_enabled = settings.visual_analysis_enabled
    settings.visual_analysis_ranking_mode = mode
    settings.visual_analysis_enabled = mode != "disabled"

    visual_metrics: dict[str, Any] = {"mode": mode, "enabled": settings.visual_analysis_enabled}
    try:
        if rerun:
            from app.services.timeline_analysis import analyze_project_timeline

            analyze_project_timeline(project_id)

        if mode in {"conservative", "shadow"}:
            cache_started = time.perf_counter()
            try:
                existing = load_project_visual_analysis(project_id)
                visual_metrics["cache_hit_seconds"] = round(time.perf_counter() - cache_started, 4)
                visual_metrics["sampled_frame_count"] = existing.sampled_frame_count
                visual_metrics["window_count"] = len(existing.windows)
            except Exception:
                visual_metrics["cache_hit_seconds"] = None

            run_started = time.perf_counter()
            document = analyze_project_visuals(project_id, force=visual_force)
            visual_metrics["run_seconds"] = round(time.perf_counter() - run_started, 4)
            visual_metrics["sampled_frame_count"] = document.sampled_frame_count
            visual_metrics["window_count"] = len(document.windows)
            visual_metrics["processing_duration_seconds"] = document.processing_duration_seconds

            cache_started = time.perf_counter()
            analyze_project_visuals(project_id, force=False)
            visual_metrics["cache_hit_seconds"] = round(time.perf_counter() - cache_started, 4)

        if rerun or mode != "disabled":
            clip_document = select_project_clips(project_id)
            payload = clip_document.model_dump(mode="json")
        else:
            try:
                clip_document = load_project_clip_candidates(project_id)
                payload = clip_document.model_dump(mode="json")
            except ClipCandidatesNotFoundError:
                clip_document = select_project_clips(project_id)
                payload = clip_document.model_dump(mode="json")
    finally:
        settings.visual_analysis_ranking_mode = original_mode
        settings.visual_analysis_enabled = original_enabled

    selected = [
        _format_candidate(candidate, rank=index + 1)
        for index, candidate in enumerate(payload.get("candidates", []))
    ]
    rejected = [
        {
            "clip_id": item.get("clip_id"),
            "start": item.get("start"),
            "end": item.get("end"),
            "duration": item.get("duration"),
            "score": item.get("score"),
            "rejection_reason": item.get("rejection_reason"),
            "importance_breakdown": item.get("importance_breakdown"),
            "reason": item.get("reason"),
        }
        for item in payload.get("rejected_candidates", [])
    ]

    ranking_changed = [
        item
        for item in selected
        if (item.get("visual_contribution") or 0) != 0
        or (item.get("score_breakdown") or {}).get("visual_would_change_ranking")
    ]

    return {
        "mode": mode,
        "selection_pipeline_version": payload.get("selection_pipeline_version"),
        "visual_analysis_pipeline_version": payload.get("visual_analysis_pipeline_version"),
        "candidate_count": payload.get("candidate_count"),
        "selected_clips": selected,
        "rejected_near_misses": rejected,
        "visual_metrics": visual_metrics,
        "ranking_changed_due_to_visual": ranking_changed,
        "phase5_comparison": _compare_to_baseline(selected, PHASE5_BASELINE),
    }


def build_evaluation_report(project_id: str, *, rerun: bool, visual_force: bool) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "quality_threshold": settings.clip_selection_quality_threshold,
        "modes": {
            "phase5_equivalent": _run_mode(
                project_id,
                mode="disabled",
                rerun=rerun,
                visual_force=False,
            ),
            "visual_shadow": _run_mode(
                project_id,
                mode="shadow",
                rerun=rerun,
                visual_force=visual_force,
            ),
            "visual_conservative": _run_mode(
                project_id,
                mode="conservative",
                rerun=rerun,
                visual_force=visual_force,
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate clip selection quality for a project.")
    parser.add_argument("project_id", help="Project UUID")
    parser.add_argument("--rerun", action="store_true", help="Re-run clip selection for each mode")
    parser.add_argument("--visual-force", action="store_true", help="Force visual analysis refresh")
    parser.add_argument("--output", type=Path, help="Optional path to write JSON report")
    args = parser.parse_args()

    report = build_evaluation_report(args.project_id, rerun=args.rerun, visual_force=args.visual_force)
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Wrote evaluation report to {args.output}")
    else:
        print(encoded)

    for mode_name, payload in report["modes"].items():
        comparison = payload["phase5_comparison"]
        print(
            f"{mode_name}: selected={payload['candidate_count']} "
            f"phase5_match={comparison['matches_phase5_baseline']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
