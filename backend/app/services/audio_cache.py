from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.services.audio_preprocessing import ChannelMixMode, PreprocessingMode, prepare_audio_for_transcription
from app.services.transcription_cache import build_source_identity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioCacheKey:
    source_identity: str
    preprocessing_mode: str
    channel_mix: str
    preprocessing_version: str

    def digest(self) -> str:
        payload = {
            "source_identity": self.source_identity,
            "preprocessing_mode": self.preprocessing_mode,
            "channel_mix": self.channel_mix,
            "preprocessing_version": self.preprocessing_version,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _audio_cache_root() -> Path:
    return settings.transcripts_dir / "_cache" / "audio"


def _channel_cache_root() -> Path:
    return settings.transcripts_dir / "_cache" / "channels"


def build_audio_cache_key(
    *,
    source_path: Path,
    mode: PreprocessingMode,
    channel_mix: ChannelMixMode,
    preprocessing_version: str,
) -> AudioCacheKey:
    return AudioCacheKey(
        source_identity=build_source_identity(source_path),
        preprocessing_mode=mode.value,
        channel_mix=channel_mix.value,
        preprocessing_version=preprocessing_version,
    )


def get_cached_audio_path(cache_key: AudioCacheKey) -> Path | None:
    path = _audio_cache_root() / cache_key.digest() / "audio.wav"
    if path.exists() and path.stat().st_size > 0:
        return path
    return None


def store_cached_audio(cache_key: AudioCacheKey, audio_path: Path) -> Path:
    cache_dir = _audio_cache_root() / cache_key.digest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / "audio.wav"
    if audio_path.resolve() != destination.resolve():
        temp_path = destination.with_suffix(".part.wav")
        shutil.copy2(audio_path, temp_path)
        temp_path.replace(destination)
    return destination


def prepare_cached_audio_for_transcription(
    source_path: Path,
    *,
    temp_dir: Path,
    mode: PreprocessingMode,
    channel_mix: ChannelMixMode = ChannelMixMode.MONO,
    preprocessing_version: str,
) -> tuple[Path, list[str], bool, bool]:
    """Return audio path, warnings, used_preprocess_fallback, cache_hit."""
    cache_key = build_audio_cache_key(
        source_path=source_path,
        mode=mode,
        channel_mix=channel_mix,
        preprocessing_version=preprocessing_version,
    )
    cached = get_cached_audio_path(cache_key)
    if cached is not None:
        logger.info(
            "Using cached preprocessed audio mode=%s mix=%s",
            mode.value,
            channel_mix.value,
        )
        return cached, [], False, True

    audio_path, warnings, used_fallback = prepare_audio_for_transcription(
        source_path,
        temp_dir=temp_dir,
        mode=mode,
        channel_mix=channel_mix,
    )
    if not used_fallback and audio_path.exists() and audio_path.stat().st_size > 0:
        stored = store_cached_audio(cache_key, audio_path)
        return stored, warnings, used_fallback, False
    return audio_path, warnings, used_fallback, False


def get_cached_channel_levels(source_path: Path) -> list[dict[str, float | str]] | None:
    cache_path = _channel_cache_root() / f"{hashlib.sha256(build_source_identity(source_path).encode('utf-8')).hexdigest()}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Invalid channel cache entry %s: %s", cache_path, exc)
    return None


def store_cached_channel_levels(source_path: Path, levels: list[dict[str, float | str]]) -> None:
    cache_dir = _channel_cache_root()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(build_source_identity(source_path).encode('utf-8')).hexdigest()}.json"
    temp_path = cache_path.with_suffix(".part.json")
    temp_path.write_text(json.dumps(levels, indent=2), encoding="utf-8")
    temp_path.replace(cache_path)
