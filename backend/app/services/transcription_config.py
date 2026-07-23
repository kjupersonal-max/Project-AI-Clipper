from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from app.core.config import settings
from app.services.audio_preprocessing import PreprocessingMode

logger = logging.getLogger(__name__)

_cuda_runtime_available: bool | None = None


class TranscriptionQualityMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH_ACCURACY = "high_accuracy"


PREPROCESSING_VERSION = "3"

# Conservative Silero VAD parameters — only used when VAD is explicitly enabled.
CONSERVATIVE_VAD_PARAMETERS = {
    "threshold": 0.35,
    "min_speech_duration_ms": 100,
    "min_silence_duration_ms": 3000,
    "speech_pad_ms": 600,
}

DEFAULT_VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 250,
    "min_silence_duration_ms": 2000,
    "speech_pad_ms": 400,
}


SUPPORTED_WHISPER_MODELS = frozenset(
    {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v2", "large-v3"}
)


@dataclass(frozen=True)
class TranscriptionModeConfig:
    mode: TranscriptionQualityMode
    model_candidates: tuple[str, ...]
    beam_size: int
    best_of: int
    temperature: tuple[float, ...]
    condition_on_previous_text: bool
    vad_filter: bool
    use_vad_recovery_pass: bool
    primary_preprocessing: PreprocessingMode
    secondary_preprocessing: PreprocessingMode | None
    no_speech_threshold: float
    log_prob_threshold: float
    compression_ratio_threshold: float
    enable_recovery_pass: bool
    recovery_beam_size: int
    max_recovery_regions: int
    max_recovery_duration_seconds: float
    early_exit_min_coverage: float
    early_exit_max_gap_seconds: float
    early_exit_min_avg_confidence: float
    warning: str | None = None


MODE_CONFIGS: dict[TranscriptionQualityMode, TranscriptionModeConfig] = {
    TranscriptionQualityMode.FAST: TranscriptionModeConfig(
        mode=TranscriptionQualityMode.FAST,
        model_candidates=("base", "tiny"),
        beam_size=1,
        best_of=1,
        temperature=(0.0,),
        condition_on_previous_text=True,
        vad_filter=False,
        use_vad_recovery_pass=False,
        primary_preprocessing=PreprocessingMode.ORIGINAL,
        secondary_preprocessing=None,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        enable_recovery_pass=False,
        recovery_beam_size=5,
        max_recovery_regions=0,
        max_recovery_duration_seconds=0.0,
        early_exit_min_coverage=settings.transcription_early_exit_min_coverage,
        early_exit_max_gap_seconds=settings.transcription_early_exit_max_gap_seconds,
        early_exit_min_avg_confidence=settings.transcription_early_exit_min_avg_confidence,
    ),
    TranscriptionQualityMode.BALANCED: TranscriptionModeConfig(
        mode=TranscriptionQualityMode.BALANCED,
        model_candidates=("small", "base"),
        beam_size=5,
        best_of=5,
        temperature=(0.0, 0.2, 0.4),
        condition_on_previous_text=True,
        vad_filter=False,
        use_vad_recovery_pass=False,
        primary_preprocessing=PreprocessingMode.ORIGINAL,
        secondary_preprocessing=PreprocessingMode.NORMALIZED,
        no_speech_threshold=0.5,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        enable_recovery_pass=True,
        recovery_beam_size=5,
        max_recovery_regions=3,
        max_recovery_duration_seconds=8.0,
        early_exit_min_coverage=settings.transcription_early_exit_min_coverage,
        early_exit_max_gap_seconds=settings.transcription_early_exit_max_gap_seconds,
        early_exit_min_avg_confidence=settings.transcription_early_exit_min_avg_confidence,
    ),
    TranscriptionQualityMode.HIGH_ACCURACY: TranscriptionModeConfig(
        mode=TranscriptionQualityMode.HIGH_ACCURACY,
        model_candidates=("medium", "small", "base"),
        beam_size=10,
        best_of=5,
        temperature=(0.0, 0.2, 0.4, 0.6),
        condition_on_previous_text=True,
        vad_filter=False,
        use_vad_recovery_pass=True,
        primary_preprocessing=PreprocessingMode.ORIGINAL,
        secondary_preprocessing=PreprocessingMode.NORMALIZED,
        no_speech_threshold=0.4,
        log_prob_threshold=-0.8,
        compression_ratio_threshold=2.2,
        enable_recovery_pass=True,
        recovery_beam_size=10,
        max_recovery_regions=5,
        max_recovery_duration_seconds=15.0,
        early_exit_min_coverage=settings.transcription_early_exit_min_coverage - 0.05,
        early_exit_max_gap_seconds=settings.transcription_early_exit_max_gap_seconds + 0.5,
        early_exit_min_avg_confidence=settings.transcription_early_exit_min_avg_confidence - 0.05,
        warning="High accuracy mode is slower and uses more compute.",
    ),
}


@dataclass
class ResolvedTranscriptionSettings:
    mode: TranscriptionQualityMode
    model_size: str
    requested_model_size: str
    device: str
    compute_type: str
    primary_preprocessing: PreprocessingMode = PreprocessingMode.ORIGINAL
    decode_options: dict[str, Any] = field(default_factory=dict)
    recovery_options: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def resolve_quality_mode(mode: str | TranscriptionQualityMode | None) -> TranscriptionQualityMode:
    if mode is None:
        return TranscriptionQualityMode.BALANCED
    if isinstance(mode, TranscriptionQualityMode):
        return mode
    normalized = mode.strip().lower().replace("-", "_")
    for candidate in TranscriptionQualityMode:
        if candidate.value == normalized:
            return candidate
    return TranscriptionQualityMode.BALANCED


def resolve_model_for_mode(mode_config: TranscriptionModeConfig) -> tuple[str, list[str]]:
    warnings: list[str] = []
    for candidate in mode_config.model_candidates:
        if candidate in SUPPORTED_WHISPER_MODELS:
            return candidate, warnings
    fallback = settings.whisper_model_size
    warnings.append(
        f"Requested models unavailable; falling back to configured model '{fallback}'."
    )
    return fallback, warnings


def reset_cuda_availability_cache() -> None:
    global _cuda_runtime_available
    _cuda_runtime_available = None


def mark_cuda_unavailable(reason: str) -> None:
    global _cuda_runtime_available
    _cuda_runtime_available = False
    logger.info(
        "CUDA is not usable on this system (%s). Continuing with CPU transcription.",
        reason,
    )


def probe_cuda_usability() -> bool:
    """Return True only when CTranslate2 can actually use CUDA on this machine."""
    global _cuda_runtime_available

    if _cuda_runtime_available is False:
        return False
    if _cuda_runtime_available is True:
        return True

    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() == 0:
            _cuda_runtime_available = False
            return False

        compute_types = ctranslate2.get_supported_compute_types("cuda")
        if not compute_types:
            _cuda_runtime_available = False
            logger.info(
                "CUDA devices were detected but no supported compute types are available. "
                "Using CPU transcription."
            )
            return False
    except Exception as exc:
        _cuda_runtime_available = False
        logger.info(
            "CUDA probe failed (%s). Using CPU transcription.",
            exc,
        )
        return False

    _cuda_runtime_available = True
    return True


def cpu_compute_type() -> str:
    return settings.whisper_compute_type or "int8"


def with_cpu_device(resolved: ResolvedTranscriptionSettings) -> ResolvedTranscriptionSettings:
    return replace(
        resolved,
        device="cpu",
        compute_type=cpu_compute_type(),
    )


def detect_device() -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    configured_device = settings.whisper_device.strip().lower()
    if configured_device and configured_device not in {"auto", "automatic"}:
        if configured_device == "cuda":
            if probe_cuda_usability():
                return "cuda", "float16", warnings
            logger.info(
                "WHISPER_DEVICE=cuda was configured but CUDA is not usable. Using CPU."
            )
            return "cpu", cpu_compute_type(), warnings
        compute_type = settings.whisper_compute_type
        return configured_device, compute_type, warnings

    if probe_cuda_usability():
        return "cuda", "float16", warnings

    return "cpu", cpu_compute_type(), warnings


def build_decode_options(
    *,
    mode_config: TranscriptionModeConfig,
    language: str | None = None,
    initial_prompt: str | None = None,
    word_timestamps: bool = True,
    vad_filter: bool | None = None,
    vad_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    use_vad = mode_config.vad_filter if vad_filter is None else vad_filter
    options: dict[str, Any] = {
        "word_timestamps": word_timestamps,
        "beam_size": mode_config.beam_size,
        "best_of": mode_config.best_of,
        "temperature": list(mode_config.temperature),
        "condition_on_previous_text": mode_config.condition_on_previous_text,
        "vad_filter": use_vad,
        "no_speech_threshold": mode_config.no_speech_threshold,
        "log_prob_threshold": mode_config.log_prob_threshold,
        "compression_ratio_threshold": mode_config.compression_ratio_threshold,
    }
    if use_vad:
        options["vad_parameters"] = vad_parameters or CONSERVATIVE_VAD_PARAMETERS
    if language:
        options["language"] = language
    if initial_prompt:
        options["initial_prompt"] = initial_prompt
    return options


def resolve_transcription_settings(
    *,
    quality_mode: str | TranscriptionQualityMode | None = None,
    language: str | None = None,
    vocabulary_hints: str | None = None,
) -> ResolvedTranscriptionSettings:
    mode = resolve_quality_mode(quality_mode)
    mode_config = MODE_CONFIGS[mode]
    model_size, model_warnings = resolve_model_for_mode(mode_config)
    device, compute_type, device_warnings = detect_device()

    warnings = [*model_warnings, *device_warnings]
    if mode_config.warning:
        warnings.append(mode_config.warning)

    initial_prompt = sanitize_vocabulary_hints(vocabulary_hints)
    decode_options = build_decode_options(
        mode_config=mode_config,
        language=language,
        initial_prompt=initial_prompt,
    )
    recovery_options = build_decode_options(
        mode_config=mode_config,
        language=language,
        initial_prompt=initial_prompt,
    )
    recovery_options["beam_size"] = mode_config.recovery_beam_size
    recovery_options["best_of"] = max(mode_config.best_of, 5)

    return ResolvedTranscriptionSettings(
        mode=mode,
        model_size=model_size,
        requested_model_size=mode_config.model_candidates[0],
        device=device,
        compute_type=compute_type,
        primary_preprocessing=mode_config.primary_preprocessing,
        decode_options=decode_options,
        recovery_options=recovery_options,
        warnings=warnings,
    )


def sanitize_vocabulary_hints(value: str | None, *, max_length: int = 500) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned


def get_mode_config(mode: TranscriptionQualityMode) -> TranscriptionModeConfig:
    return MODE_CONFIGS[mode]


@dataclass(frozen=True)
class DiscoveryModeConfig:
    beam_size: int = 1
    best_of: int = 1
    temperature: tuple[float, ...] = (0.0,)
    condition_on_previous_text: bool = True
    vad_filter: bool = False
    word_timestamps: bool = False
    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -1.0
    compression_ratio_threshold: float = 2.4


DISCOVERY_MODE_CONFIG = DiscoveryModeConfig(
    condition_on_previous_text=settings.discovery_condition_on_previous_text,
)


def resolve_discovery_model(language: str | None) -> str:
    normalized = (language or "").strip().lower()
    if normalized in {"en", "english"}:
        if "tiny.en" in SUPPORTED_WHISPER_MODELS:
            return "tiny.en"
        if "base.en" in SUPPORTED_WHISPER_MODELS:
            return "base.en"
    if "tiny" in SUPPORTED_WHISPER_MODELS:
        return "tiny"
    return "base"


def resolve_discovery_settings(
    *,
    language: str | None = None,
    vocabulary_hints: str | None = None,
) -> ResolvedTranscriptionSettings:
    model_size = resolve_discovery_model(language)
    device, compute_type, device_warnings = detect_device()
    if device == "cpu":
        compute_type = cpu_compute_type()

    initial_prompt = sanitize_vocabulary_hints(vocabulary_hints)
    decode_options = {
        "word_timestamps": DISCOVERY_MODE_CONFIG.word_timestamps,
        "beam_size": DISCOVERY_MODE_CONFIG.beam_size,
        "best_of": DISCOVERY_MODE_CONFIG.best_of,
        "temperature": list(DISCOVERY_MODE_CONFIG.temperature),
        "condition_on_previous_text": DISCOVERY_MODE_CONFIG.condition_on_previous_text,
        "vad_filter": DISCOVERY_MODE_CONFIG.vad_filter,
        "no_speech_threshold": DISCOVERY_MODE_CONFIG.no_speech_threshold,
        "log_prob_threshold": DISCOVERY_MODE_CONFIG.log_prob_threshold,
        "compression_ratio_threshold": DISCOVERY_MODE_CONFIG.compression_ratio_threshold,
    }
    if language:
        decode_options["language"] = language
    if initial_prompt:
        decode_options["initial_prompt"] = initial_prompt

    return ResolvedTranscriptionSettings(
        mode=TranscriptionQualityMode.FAST,
        model_size=model_size,
        requested_model_size=model_size,
        device=device,
        compute_type=compute_type,
        primary_preprocessing=PreprocessingMode.ORIGINAL,
        decode_options=decode_options,
        recovery_options={},
        warnings=device_warnings,
    )
