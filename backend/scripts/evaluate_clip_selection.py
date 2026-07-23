#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.clip_selection import (
    ClipCandidatesNotFoundError,
    load_project_clip_candidates,
    select_project_clips,
)


def _format_candidate(candidate: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    importance = candidate.get("importance_breakdown") or {}
    return {
        "rank": rank,
        "clip_id": candidate.get("clip_id"),
        "start": candidate.get("start"),
        "end": candidate.get("end"),
        "duration": candidate.get("duration"),
        "score": candidate.get("score"),
        "primary_emotion": candidate.get("primary_emotion"),
        "selection_reasons": candidate.get("selection_reasons", []),
        "warnings": candidate.get("warnings", []),
        "reason": candidate.get("reason"),
        "score_breakdown": candidate.get("score_breakdown", {}),
        "importance_breakdown": importance,
        "transcript_preview": (candidate.get("transcript_text") or "")[:160],
    }


def build_evaluation_report(project_id: str, *, rerun: bool) -> dict[str, Any]:
    if rerun:
        document = select_project_clips(project_id)
        payload = document.model_dump(mode="json")
    else:
        try:
            document = load_project_clip_candidates(project_id)
            payload = document.model_dump(mode="json")
        except ClipCandidatesNotFoundError:
            document = select_project_clips(project_id)
            payload = document.model_dump(mode="json")

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

    return {
        "project_id": project_id,
        "selection_pipeline_version": payload.get("selection_pipeline_version"),
        "quality_threshold": payload.get("quality_threshold"),
        "candidate_count": payload.get("candidate_count"),
        "selected_clips": selected,
        "rejected_near_misses": rejected,
        "human_ratings_template": {
            "instructions": "Rate each selected clip: excellent | good | weak | bad",
            "ratings": [
                {"clip_id": item["clip_id"], "rating": None, "notes": ""}
                for item in selected
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate clip selection quality for a project.")
    parser.add_argument("project_id", help="Project UUID")
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Re-run clip selection before generating the report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write JSON report",
    )
    parser.add_argument(
        "--ratings",
        type=Path,
        help="Optional human ratings JSON to merge into report",
    )
    args = parser.parse_args()

    report = build_evaluation_report(args.project_id, rerun=args.rerun)
    if args.ratings and args.ratings.exists():
        ratings_payload = json.loads(args.ratings.read_text(encoding="utf-8"))
        report["human_ratings"] = ratings_payload

    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Wrote evaluation report to {args.output}")
    else:
        print(encoded)

    print(
        f"\nPipeline v{settings.clip_selection_pipeline_version} | "
        f"selected={report['candidate_count']} | "
        f"rejected_near_misses={len(report['rejected_near_misses'])}",
        flush=True,
    )


if __name__ == "__main__":
    main()
