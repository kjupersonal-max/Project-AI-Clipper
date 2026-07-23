from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.project import TranscriptDocument, TranscriptTier
from app.services.transcription_config import PREPROCESSING_VERSION, TranscriptionQualityMode

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionCacheKey:
    source_identity: str
    clip_start: float | None
    clip_end: float | None
    quality_mode: TranscriptionQualityMode | None
    model_size: str
    language: str | None
    vocabulary_hints: str | None
    preprocessing_version: str = PREPROCESSING_VERSION
    transcript_tier: TranscriptTier = TranscriptTier.FULL_QUALITY
    chunk_index: int | None = None

    def digest(self) -> str:
        payload = {
            "source_identity": self.source_identity,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
            "quality_mode": self.quality_mode.value if self.quality_mode else "",
            "model_size": self.model_size,
            "language": self.language or "",
            "vocabulary_hints": self.vocabulary_hints or "",
            "preprocessing_version": self.preprocessing_version,
            "transcript_tier": self.transcript_tier.value,
            "chunk_index": self.chunk_index,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _cache_root() -> Path:
    return settings.transcripts_dir / "_cache"


def _cache_path(cache_key: TranscriptionCacheKey) -> Path:
    return _cache_root() / cache_key.digest() / "transcript.json"


def build_source_identity(audio_path: Path) -> str:
    stat = audio_path.stat()
    return f"{audio_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def get_cached_transcript(cache_key: TranscriptionCacheKey) -> TranscriptDocument | None:
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        document = TranscriptDocument.model_validate(payload)
        if document.segments:
            return document
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid transcription cache entry %s: %s", path, exc)
        invalidate_cache_entry(cache_key)
    return None


def store_cached_transcript(cache_key: TranscriptionCacheKey, document: TranscriptDocument) -> None:
    if not document.segments:
        return
    path = _cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".part")
    temp_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")
    temp_path.replace(path)


def invalidate_cache_entry(cache_key: TranscriptionCacheKey) -> None:
    cache_dir = _cache_root() / cache_key.digest()
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)


def build_cache_key(
    *,
    audio_path: Path,
    quality_mode: TranscriptionQualityMode | None = None,
    model_size: str,
    language: str | None = None,
    vocabulary_hints: str | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    transcript_tier: TranscriptTier = TranscriptTier.FULL_QUALITY,
    chunk_index: int | None = None,
) -> TranscriptionCacheKey:
    return TranscriptionCacheKey(
        source_identity=build_source_identity(audio_path),
        clip_start=clip_start,
        clip_end=clip_end,
        quality_mode=quality_mode,
        model_size=model_size,
        language=language,
        vocabulary_hints=vocabulary_hints,
        transcript_tier=transcript_tier,
        chunk_index=chunk_index,
    )
