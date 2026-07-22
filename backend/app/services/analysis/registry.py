from __future__ import annotations

from app.core.config import settings
from app.services.analysis.base import AnalysisProvider, ProviderConfigurationError
from app.services.analysis.external import ExternalLLMAnalysisProvider
from app.services.analysis.heuristic import HeuristicAnalysisProvider

EXTERNAL_PROVIDERS = {"openai", "anthropic", "openai_compatible"}


def resolve_analysis_provider() -> AnalysisProvider:
    configured = settings.analysis_provider.strip().lower()

    if configured in {"", "auto", "heuristic", "local"}:
        if configured == "auto" and settings.analysis_api_key:
            return _build_external_provider(settings.analysis_external_provider)
        return HeuristicAnalysisProvider()

    if configured in EXTERNAL_PROVIDERS or configured == "external":
        if not settings.analysis_api_key:
            raise ProviderConfigurationError(
                f"Analysis provider '{configured}' requires ANALYSIS_API_KEY to be configured."
            )
        provider_name = configured if configured != "external" else settings.analysis_external_provider
        return _build_external_provider(provider_name)

    raise ProviderConfigurationError(
        f"Unsupported analysis provider '{settings.analysis_provider}'."
    )


def _build_external_provider(provider_name: str) -> AnalysisProvider:
    if not settings.analysis_api_key:
        raise ProviderConfigurationError(
            f"Analysis provider '{provider_name}' requires ANALYSIS_API_KEY to be configured."
        )

    return ExternalLLMAnalysisProvider(
        provider_name=provider_name,
        model_name=settings.analysis_model,
        api_key=settings.analysis_api_key,
        base_url=settings.analysis_api_base_url,
    )
