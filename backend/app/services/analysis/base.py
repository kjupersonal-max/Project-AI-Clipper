from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.project import SegmentAnalysis, TranscriptSegment


class AnalysisProviderError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ProviderConfigurationError(AnalysisProviderError):
    pass


class AnalysisProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def analyze_batch(self, segments: list[TranscriptSegment]) -> list[SegmentAnalysis]:
        raise NotImplementedError
