from __future__ import annotations

from app.core.config import settings
from app.services.analysis.registry import describe_analysis_provider


def get_analysis_provider_diagnostics(*, dry_run: bool = False) -> dict[str, object]:
    description = describe_analysis_provider()

    diagnostics: dict[str, object] = {
        "configured_provider": settings.analysis_provider,
        "resolved_provider": description["provider_name"],
        "resolved_model": description["model_name"],
        "is_heuristic_fallback": description["is_heuristic_fallback"],
        "api_key_configured": bool(settings.analysis_api_key.strip()),
        "batch_size": settings.analysis_batch_size,
        "timeout_seconds": settings.analysis_timeout_seconds,
        "max_transcript_chars": settings.analysis_max_transcript_chars,
        "available": description["available"],
        "message": description["message"],
    }

    if dry_run and description["available"] and not description["is_heuristic_fallback"]:
        diagnostics["dry_run"] = "configuration_valid"
    elif dry_run:
        diagnostics["dry_run"] = "not_applicable"

    return diagnostics
