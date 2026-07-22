from __future__ import annotations

from app.core.config import settings
from app.services.analysis.base import AnalysisProvider, ProviderConfigurationError
from app.services.analysis.external import ExternalLLMAnalysisProvider
from app.services.analysis.heuristic import HeuristicAnalysisProvider
from app.services.analysis.openai_provider import OpenAIAnalysisProvider

EXTERNAL_PROVIDERS = {"openai", "anthropic", "openai_compatible"}


def resolve_analysis_provider() -> AnalysisProvider:
    configured = settings.analysis_provider.strip().lower()

    if configured in {"", "auto", "heuristic", "local"}:
        if configured == "auto" and settings.analysis_api_key.strip():
            return _build_external_provider(settings.analysis_external_provider)
        return HeuristicAnalysisProvider()

    if configured in EXTERNAL_PROVIDERS or configured == "external":
        if not settings.analysis_api_key.strip():
            raise ProviderConfigurationError(
                f"Analysis provider '{configured}' requires ANALYSIS_API_KEY to be configured."
            )
        provider_name = configured if configured != "external" else settings.analysis_external_provider
        return _build_external_provider(provider_name)

    raise ProviderConfigurationError(
        f"Unsupported analysis provider '{settings.analysis_provider}'."
    )


def describe_analysis_provider() -> dict[str, object]:
    configured = settings.analysis_provider.strip().lower()
    api_key_configured = bool(settings.analysis_api_key.strip())

    try:
        provider = resolve_analysis_provider()
    except ProviderConfigurationError as exc:
        return {
            "provider_name": configured or "auto",
            "model_name": settings.analysis_model if api_key_configured else None,
            "is_heuristic_fallback": True,
            "available": False,
            "message": exc.message,
        }

    is_heuristic = provider.provider_name == "heuristic"
    return {
        "provider_name": provider.provider_name,
        "model_name": provider.model_name,
        "is_heuristic_fallback": is_heuristic,
        "available": True,
        "message": (
            "Using heuristic fallback analyzer."
            if is_heuristic
            else f"Configured for {provider.provider_name} with model {provider.model_name}."
        ),
    }


def _build_external_provider(provider_name: str) -> AnalysisProvider:
    if not settings.analysis_api_key.strip():
        raise ProviderConfigurationError(
            f"Analysis provider '{provider_name}' requires ANALYSIS_API_KEY to be configured."
        )

    normalized = provider_name.strip().lower()
    if normalized in {"openai", "openai_compatible"}:
        return OpenAIAnalysisProvider(
            model_name=settings.analysis_model,
            api_key=settings.analysis_api_key,
            base_url=settings.analysis_api_base_url,
        )

    return ExternalLLMAnalysisProvider(
        provider_name=normalized,
        model_name=settings.analysis_model,
        api_key=settings.analysis_api_key,
        base_url=settings.analysis_api_base_url,
    )
