from __future__ import annotations

from app.models.project import SegmentAnalysis, TranscriptSegment
from app.services.analysis.base import AnalysisProvider, ProviderConfigurationError


class ExternalLLMAnalysisProvider(AnalysisProvider):
    """Placeholder for a future configurable LLM-backed analysis provider."""

    def __init__(self, *, provider_name: str, model_name: str, api_key: str, base_url: str | None):
        self._provider_name = provider_name
        self._model_name = model_name
        self._api_key = api_key
        self._base_url = base_url

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str | None:
        return self._model_name

    def analyze_batch(self, segments: list[TranscriptSegment]) -> list[SegmentAnalysis]:
        raise ProviderConfigurationError(
            f"External analysis provider '{self._provider_name}' is configured "
            f"with model '{self._model_name}', but no LLM implementation is wired yet. "
            "Use ANALYSIS_PROVIDER=heuristic for local development."
        )
