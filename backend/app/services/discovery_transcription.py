from __future__ import annotations

import json
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.models.project import (
    ChunkProcessingStatus,
    PipelineStage,
    ProcessingStatus,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptTier,
    TranscriptionQualityMode,
)
from app.services.audio_preprocessing import cleanup_temp_audio
from app.services.pipeline_timing import log_stage_event, log_timing_summary, log_transcription_trace
from app.services.project_store import load_project, save_project
from app.services.transcript_store import (
    get_discovery_chunk_state_path,
    get_discovery_chunk_transcript_path,
    get_discovery_transcript_path,
    get_relative_discovery_transcript_path,
)
from app.services.transcription import (
    TranscriptionAudioNotFoundError,
    TranscriptionProcessError,
    WhisperModelLoadError,
    _build_transcript_document,
    get_whisper_model_for_settings,
    locate_project_audio,
    transcribe_audio_to_segments,
)
from app.services.transcription_cache import build_cache_key, get_cached_transcript, store_cached_transcript
from app.services.transcription_config import resolve_discovery_settings, sanitize_vocabulary_hints
from app.services.discovery_timing import DiscoveryBenchmarkReport, DiscoveryTimingCollector
from app.services.video_processing import extract_audio_chunk_from_wav, inspect_video_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioChunkPlan:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class ChunkStateEntry:
    index: int
    start: float
    end: float
    status: ChunkProcessingStatus = ChunkProcessingStatus.PENDING
    cache_hit: bool = False
    error: str | None = None
    segment_count: int = 0


@dataclass
class DiscoveryChunkState:
    audio_duration: float
    chunk_seconds: float
    overlap_seconds: float
    worker_count: int
    chunks: list[ChunkStateEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_duration": self.audio_duration,
            "chunk_seconds": self.chunk_seconds,
            "overlap_seconds": self.overlap_seconds,
            "worker_count": self.worker_count,
            "chunks": [
                {
                    "index": chunk.index,
                    "start": chunk.start,
                    "end": chunk.end,
                    "status": chunk.status.value,
                    "cache_hit": chunk.cache_hit,
                    "error": chunk.error,
                    "segment_count": chunk.segment_count,
                }
                for chunk in self.chunks
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DiscoveryChunkState:
        return cls(
            audio_duration=float(payload["audio_duration"]),
            chunk_seconds=float(payload["chunk_seconds"]),
            overlap_seconds=float(payload["overlap_seconds"]),
            worker_count=int(payload.get("worker_count", 1)),
            chunks=[
                ChunkStateEntry(
                    index=int(item["index"]),
                    start=float(item["start"]),
                    end=float(item["end"]),
                    status=ChunkProcessingStatus(item.get("status", ChunkProcessingStatus.PENDING.value)),
                    cache_hit=bool(item.get("cache_hit", False)),
                    error=item.get("error"),
                    segment_count=int(item.get("segment_count", 0)),
                )
                for item in payload.get("chunks", [])
            ],
        )


def plan_audio_chunks(
    *,
    duration: float,
    chunk_seconds: float | None = None,
    overlap_seconds: float | None = None,
) -> list[AudioChunkPlan]:
    if duration <= 0:
        return []

    chunk_size = chunk_seconds or settings.discovery_chunk_seconds
    overlap = overlap_seconds or settings.discovery_chunk_overlap_seconds
    if duration <= settings.discovery_short_video_chunk_threshold_seconds:
        return [AudioChunkPlan(index=0, start=0.0, end=round(duration, 3))]

    stride = max(1.0, chunk_size - overlap)
    chunks: list[AudioChunkPlan] = []
    start = 0.0
    index = 0
    while start < duration:
        end = min(duration, start + chunk_size)
        chunks.append(AudioChunkPlan(index=index, start=round(start, 3), end=round(end, 3)))
        if end >= duration:
            break
        start += stride
        index += 1
    return chunks


def offset_segments(segments: list[TranscriptSegment], offset_seconds: float) -> list[TranscriptSegment]:
    if offset_seconds <= 0:
        return segments
    return [
        TranscriptSegment(
            id=segment.id,
            start=round(segment.start + offset_seconds, 3),
            end=round(segment.end + offset_seconds, 3),
            text=segment.text,
            words=[],
        )
        for segment in segments
    ]


def deduplicate_overlap_segments(
    left_segments: list[TranscriptSegment],
    right_segments: list[TranscriptSegment],
    *,
    overlap_start: float,
    overlap_end: float,
) -> list[TranscriptSegment]:
    left_overlap_text = {
        segment.text.strip().lower()
        for segment in left_segments
        if segment.end > overlap_start and segment.start < overlap_end and segment.text.strip()
    }
    kept: list[TranscriptSegment] = []
    for segment in right_segments:
        if segment.start < overlap_end and segment.text.strip().lower() in left_overlap_text:
            continue
        kept.append(segment)
    return kept


def merge_chunk_segments(
    chunk_segments: list[list[TranscriptSegment]],
    *,
    chunk_plans: list[AudioChunkPlan],
    overlap_seconds: float,
) -> list[TranscriptSegment]:
    if not chunk_segments:
        return []
    merged = list(chunk_segments[0])
    for index in range(1, len(chunk_segments)):
        plan = chunk_plans[index]
        overlap_start = plan.start
        overlap_end = min(plan.end, plan.start + overlap_seconds)
        deduped = deduplicate_overlap_segments(
            merged,
            chunk_segments[index],
            overlap_start=overlap_start,
            overlap_end=overlap_end,
        )
        merged.extend(deduped)
    for segment_id, segment in enumerate(merged):
        segment.id = segment_id
    return merged


def save_chunk_state(project_id: str, state: DiscoveryChunkState) -> None:
    path = get_discovery_chunk_state_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".part")
    temp_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    temp_path.replace(path)


def load_chunk_state(project_id: str) -> DiscoveryChunkState | None:
    path = get_discovery_chunk_state_path(project_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DiscoveryChunkState.from_dict(payload)


def _write_chunk_transcript(project_id: str, chunk_index: int, document: TranscriptDocument) -> None:
    if not settings.discovery_persist_chunk_transcripts:
        return
    path = get_discovery_chunk_transcript_path(project_id, chunk_index)
    temp_path = path.with_suffix(".part")
    temp_path.write_text(
        json.dumps(document.model_dump(mode="json"), separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _load_chunk_transcript(project_id: str, chunk_index: int) -> TranscriptDocument | None:
    path = get_discovery_chunk_transcript_path(project_id, chunk_index)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TranscriptDocument.model_validate(payload)


def _write_discovery_transcript(project_id: str, document: TranscriptDocument) -> str:
    output_path = get_discovery_transcript_path(project_id)
    partial_path = output_path.with_suffix(".part")
    partial_path.write_text(
        json.dumps(document.model_dump(mode="json"), separators=(",", ":")),
        encoding="utf-8",
    )
    partial_path.replace(output_path)
    return get_relative_discovery_transcript_path(project_id)


def _probe_audio_duration(audio_path: Path) -> float:
    try:
        metadata = inspect_video_file(audio_path)
        if metadata.duration_seconds and metadata.duration_seconds > 0:
            return float(metadata.duration_seconds)
    except Exception:
        logger.warning("Unable to probe audio duration via ffprobe for %s; using fallback estimate.", audio_path)
    return max(audio_path.stat().st_size / (16000 * 2), 10.0)


def _update_discovery_progress(
    project_id: str,
    *,
    stage: str,
    progress_pct: float,
    chunks_completed: int,
    chunks_total: int,
    pipeline_stage: str | None = None,
) -> None:
    project = load_project(project_id)
    project.discovery_transcription_stage = stage
    project.discovery_transcription_progress_pct = round(progress_pct, 1)
    project.discovery_chunks_completed = chunks_completed
    project.discovery_chunks_total = chunks_total
    project.discovery_chunks_remaining = max(0, chunks_total - chunks_completed)
    project.transcription_stage = stage
    project.transcription_progress_pct = round(progress_pct, 1)
    if pipeline_stage:
        project.pipeline_stage = pipeline_stage
    save_project(project)


def transcribe_discovery_chunk(
    *,
    project_id: str,
    audio_path: Path,
    chunk: AudioChunkPlan,
    resolved: Any,
    temp_dir: Path,
    vocabulary_hints: str | None,
    whisper_model: Any | None = None,
    use_full_audio: bool = False,
    use_cache: bool = True,
    metrics: dict[str, float] | None = None,
) -> tuple[list[TranscriptSegment], str, bool, Any]:
    cache_key = build_cache_key(
        audio_path=audio_path,
        quality_mode=None,
        model_size=resolved.model_size,
        language=resolved.decode_options.get("language"),
        vocabulary_hints=vocabulary_hints,
        clip_start=chunk.start,
        clip_end=chunk.end,
        transcript_tier=TranscriptTier.DISCOVERY,
        chunk_index=chunk.index,
    )
    if use_cache:
        cached = get_cached_transcript(cache_key)
        if cached is not None:
            if metrics is not None:
                metrics["cache_hits"] = metrics.get("cache_hits", 0) + 1
            return cached.segments, cached.language, True, resolved

    extract_started = time.perf_counter()
    if use_full_audio:
        chunk_audio = audio_path
    else:
        chunk_dir = temp_dir / f"chunk_{chunk.index:04d}"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_audio = chunk_dir / "audio.wav"
        extract_audio_chunk_from_wav(
            source_audio=audio_path,
            output_path=chunk_audio,
            start_time=chunk.start,
            duration=chunk.duration,
        )
    if metrics is not None:
        metrics["chunk_extraction"] = metrics.get("chunk_extraction", 0.0) + (
            time.perf_counter() - extract_started
        )

    transcribe_started = time.perf_counter()
    segments, info, effective, _model = transcribe_audio_to_segments(
        resolved,
        chunk_audio,
        model=whisper_model,
        **resolved.decode_options,
    )
    if metrics is not None:
        metrics["per_chunk_transcription"] = metrics.get("per_chunk_transcription", 0.0) + (
            time.perf_counter() - transcribe_started
        )
    segments = offset_segments(segments, chunk.start)
    language = info.language or "unknown"

    if settings.discovery_persist_chunk_transcripts or use_cache:
        persist_started = time.perf_counter()
        chunk_document = _build_transcript_document(
            project_id=project_id,
            language=language,
            duration=chunk.duration,
            segments=segments,
            quality_mode=TranscriptionQualityMode.FAST,
            quality_rating=None,
            quality_warnings=["Discovery tier transcript; not for final captions."],
            vocabulary_hints=vocabulary_hints,
            transcription_revision=1,
        )
        chunk_document.transcript_tier = TranscriptTier.DISCOVERY
        chunk_document.chunk_index = chunk.index
        chunk_document.chunk_start = chunk.start
        chunk_document.chunk_end = chunk.end
        _write_chunk_transcript(project_id, chunk.index, chunk_document)
        if use_cache:
            store_cached_transcript(cache_key, chunk_document)
        if metrics is not None:
            metrics["chunk_persist"] = metrics.get("chunk_persist", 0.0) + (
                time.perf_counter() - persist_started
            )
    return segments, language, False, effective


def _build_transcript_document_with_tier(**kwargs: Any) -> TranscriptDocument:
    document = _build_transcript_document(**kwargs)
    document.transcript_tier = TranscriptTier.DISCOVERY
    return document


def run_discovery_transcription(
    project_id: str,
    *,
    vocabulary_hints: str | None = None,
    language: str | None = None,
    use_cache: bool = True,
    progress_callback: Callable[[str, float, str], None] | None = None,
    chunk_completed_callback: Callable[[int, list[TranscriptSegment]], None] | None = None,
    timing_collector: DiscoveryTimingCollector | None = None,
) -> TranscriptDocument:
    pipeline_started = time.perf_counter()
    log_stage_event("discovery_transcription", "start", project_id=project_id)
    timing = timing_collector or DiscoveryTimingCollector(enabled=False)

    timing.start_stage("setup")
    audio_path = locate_project_audio(project_id)
    project = load_project(project_id)
    hints = sanitize_vocabulary_hints(vocabulary_hints or project.vocabulary_hints)
    resolved = resolve_discovery_settings(language=language or project.detected_language, vocabulary_hints=hints)
    audio_duration = _probe_audio_duration(audio_path)
    chunk_plans = plan_audio_chunks(duration=audio_duration)
    worker_count = max(1, settings.discovery_worker_count)
    use_single_chunk_path = len(chunk_plans) == 1
    timing.end_stage("setup", chunk_count=len(chunk_plans))

    existing_state = load_chunk_state(project_id)
    if existing_state and len(existing_state.chunks) == len(chunk_plans):
        chunk_state = existing_state
    else:
        chunk_state = DiscoveryChunkState(
            audio_duration=audio_duration,
            chunk_seconds=settings.discovery_chunk_seconds,
            overlap_seconds=settings.discovery_chunk_overlap_seconds,
            worker_count=worker_count,
            chunks=[
                ChunkStateEntry(index=plan.index, start=plan.start, end=plan.end)
                for plan in chunk_plans
            ],
        )
        if settings.discovery_persist_chunk_state:
            save_chunk_state(project_id, chunk_state)

    project = load_project(project_id)
    project.discovery_transcription_status = ProcessingStatus.PROCESSING
    project.pipeline_stage = PipelineStage.DISCOVERY_TRANSCRIPTION.value
    project.discovery_transcription_stage = PipelineStage.DISCOVERY_TRANSCRIPTION.value
    save_project(project)

    temp_dir = settings.transcripts_dir / settings.transcription_temp_dir_name / project_id / "discovery"
    chunk_segments_by_index: dict[int, list[TranscriptSegment]] = {}
    detected_language = language or project.detected_language or "unknown"
    cache_hits = 0
    stage_metrics: dict[str, float] = {"cache_hits": 0.0}
    chunk_state_io_seconds = 0.0
    progress_io_seconds = 0.0

    def _report(chunk_index: int, total: int, detail: str) -> None:
        nonlocal progress_io_seconds
        progress_started = time.perf_counter()
        completed = sum(
            1 for entry in chunk_state.chunks if entry.status in {ChunkProcessingStatus.COMPLETED, ChunkProcessingStatus.CACHED}
        )
        progress = round((completed / max(1, total)) * 100.0, 1)
        stage = f"{PipelineStage.DISCOVERY_CHUNK.value}_{chunk_index + 1}_of_{total}"
        _update_discovery_progress(
            project_id,
            stage=stage,
            progress_pct=progress,
            chunks_completed=completed,
            chunks_total=total,
            pipeline_stage=PipelineStage.DISCOVERY_TRANSCRIPTION.value,
        )
        progress_io_seconds += time.perf_counter() - progress_started
        if progress_callback is not None:
            progress_callback(stage, progress, detail)

    try:
        model_load_started = time.perf_counter()
        timing.start_stage("model_load")
        whisper_model = get_whisper_model_for_settings(resolved)
        effective_resolved = resolved
        model_load_seconds = time.perf_counter() - model_load_started
        timing.end_stage(
            "model_load",
            extra={"model": resolved.model_size, "device": resolved.device},
        )

        pending: list[AudioChunkPlan] = []
        for plan in chunk_plans:
            entry = chunk_state.chunks[plan.index]
            if entry.status in {ChunkProcessingStatus.COMPLETED, ChunkProcessingStatus.CACHED}:
                if settings.discovery_persist_chunk_transcripts:
                    stored = _load_chunk_transcript(project_id, plan.index)
                    if stored is not None and stored.segments:
                        chunk_segments_by_index[plan.index] = stored.segments
                        if entry.cache_hit:
                            cache_hits += 1
                        continue
            pending.append(plan)

        def _process_chunk(plan: AudioChunkPlan) -> tuple[int, list[TranscriptSegment], str, bool, str | None]:
            nonlocal chunk_state_io_seconds, effective_resolved
            entry = chunk_state.chunks[plan.index]
            entry.status = ChunkProcessingStatus.PROCESSING
            try:
                segments, chunk_language, cache_hit, chunk_resolved = transcribe_discovery_chunk(
                    project_id=project_id,
                    audio_path=audio_path,
                    chunk=plan,
                    resolved=effective_resolved,
                    temp_dir=temp_dir,
                    vocabulary_hints=hints,
                    whisper_model=whisper_model,
                    use_full_audio=use_single_chunk_path,
                    use_cache=use_cache,
                    metrics=stage_metrics,
                )
                effective_resolved = chunk_resolved
                entry.status = ChunkProcessingStatus.CACHED if cache_hit else ChunkProcessingStatus.COMPLETED
                entry.cache_hit = cache_hit
                entry.segment_count = len(segments)
                if settings.discovery_persist_chunk_state:
                    state_started = time.perf_counter()
                    save_chunk_state(project_id, chunk_state)
                    chunk_state_io_seconds += time.perf_counter() - state_started
                return plan.index, segments, chunk_language, cache_hit, None
            except Exception as exc:
                entry.status = ChunkProcessingStatus.FAILED
                entry.error = str(exc)
                if settings.discovery_persist_chunk_state:
                    save_chunk_state(project_id, chunk_state)
                return plan.index, [], detected_language, False, str(exc)

        timing.start_stage("chunk_transcription")
        if worker_count <= 1:
            for plan in pending:
                _report(plan.index, len(chunk_plans), f"Transcribing chunk {plan.index + 1}/{len(chunk_plans)}")
                index, segments, chunk_language, cache_hit, error = _process_chunk(plan)
                if error:
                    raise TranscriptionProcessError(f"Discovery chunk {index} failed: {error}")
                chunk_segments_by_index[index] = segments
                detected_language = chunk_language or detected_language
                if chunk_completed_callback is not None:
                    chunk_completed_callback(index, segments)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(_process_chunk, plan): plan for plan in pending}
                for future in as_completed(futures):
                    plan = futures[future]
                    _report(plan.index, len(chunk_plans), f"Transcribing chunk {plan.index + 1}/{len(chunk_plans)}")
                    index, segments, chunk_language, cache_hit, error = future.result()
                    if error:
                        raise TranscriptionProcessError(f"Discovery chunk {index} failed: {error}")
                    chunk_segments_by_index[index] = segments
                    detected_language = chunk_language or detected_language
                    if chunk_completed_callback is not None:
                        chunk_completed_callback(index, segments)
        cache_hits = int(stage_metrics.get("cache_hits", 0))
        timing.end_stage(
            "chunk_transcription",
            chunk_count=len(pending),
            audio_seconds=audio_duration,
            cache_hits=cache_hits,
            real_time_factor=(
                stage_metrics.get("per_chunk_transcription", 0.0) / max(audio_duration, 0.001)
            ),
        )
        if stage_metrics.get("chunk_extraction", 0.0) > 0:
            timing.record_stage(
                "chunk_extraction",
                stage_metrics["chunk_extraction"],
                chunk_count=len(pending),
            )
        if stage_metrics.get("per_chunk_transcription", 0.0) > 0:
            timing.record_stage(
                "per_chunk_transcription",
                stage_metrics["per_chunk_transcription"],
                audio_seconds=audio_duration,
                chunk_count=len(pending),
            )
        if stage_metrics.get("chunk_persist", 0.0) > 0:
            timing.record_stage(
                "chunk_persist",
                stage_metrics["chunk_persist"],
                chunk_count=len(pending),
            )
        if progress_io_seconds > 0:
            timing.record_stage("progress_persistence", progress_io_seconds)
        if chunk_state_io_seconds > 0:
            timing.record_stage("chunk_state_io", chunk_state_io_seconds)

        timing.start_stage("chunk_merge")
        ordered_segments = merge_chunk_segments(
            [chunk_segments_by_index[plan.index] for plan in chunk_plans],
            chunk_plans=chunk_plans,
            overlap_seconds=settings.discovery_chunk_overlap_seconds,
        )
        timing.end_stage("chunk_merge", chunk_count=len(chunk_plans))
        if not ordered_segments:
            raise TranscriptionProcessError("Discovery transcription produced no segments.")

        timing.start_stage("transcript_persist")
        persist_started = time.perf_counter()
        document = _build_transcript_document_with_tier(
            project_id=project_id,
            language=detected_language,
            duration=round(audio_duration, 3),
            segments=ordered_segments,
            quality_mode=TranscriptionQualityMode.FAST,
            quality_rating=None,
            quality_warnings=[
                "Discovery tier transcript for timeline analysis and clip discovery.",
                "Final clip captions require local high-quality retranscription.",
            ],
            vocabulary_hints=hints,
        )
        relative_path = _write_discovery_transcript(project_id, document)
        transcript_persist_seconds = time.perf_counter() - persist_started
        timing.end_stage("transcript_persist")

        chunk_state_persist_seconds = 0.0
        if settings.discovery_persist_chunk_state:
            timing.start_stage("chunk_state_persist")
            chunk_state_started = time.perf_counter()
            save_chunk_state(project_id, chunk_state)
            chunk_state_persist_seconds = time.perf_counter() - chunk_state_started
            timing.end_stage("chunk_state_persist")

        elapsed = time.perf_counter() - pipeline_started
        rtf = elapsed / max(audio_duration, 0.001)
        project = load_project(project_id)
        project.discovery_transcription_status = ProcessingStatus.COMPLETED
        project.discovery_transcription_stage = PipelineStage.DISCOVERY_TRANSCRIPTION.value
        project.discovery_transcription_progress_pct = 100.0
        project.discovery_transcript_path = relative_path
        project.transcript_path = relative_path
        project.active_transcript_tier = TranscriptTier.DISCOVERY
        project.transcription_status = ProcessingStatus.COMPLETED
        project.transcription_stage = PipelineStage.DISCOVERY_TRANSCRIPTION.value
        project.transcription_progress_pct = 100.0
        project.detected_language = detected_language
        project.discovery_chunks_completed = len(chunk_plans)
        project.discovery_chunks_total = len(chunk_plans)
        project.discovery_chunks_remaining = 0
        project.pipeline_stage = PipelineStage.DISCOVERY_TRANSCRIPTION.value
        save_project(project)

        transcription_seconds = stage_metrics.get("per_chunk_transcription", 0.0)
        persistence_seconds = (
            transcript_persist_seconds
            + chunk_state_persist_seconds
            + progress_io_seconds
            + chunk_state_io_seconds
        )
        log_transcription_trace(
            event="completed",
            project_id=project_id,
            transcription_tier="discovery",
            transcription_path="discovery",
            model_name=effective_resolved.model_size,
            use_full_quality=False,
            chunk_count=len(chunk_plans),
            model_load_seconds=model_load_seconds,
            transcription_seconds=transcription_seconds,
            persistence_seconds=persistence_seconds,
            total_wall_seconds=elapsed,
            device=effective_resolved.device,
            cache_hits=cache_hits,
            audio_duration_seconds=round(audio_duration, 3),
            real_time_factor=round(rtf, 3),
        )
        log_timing_summary(
            project_id=project_id,
            pipeline="discovery_transcription",
            total_seconds=elapsed,
            audio_duration=f"{audio_duration:.3f}s",
            real_time_factor=f"{rtf:.3f}",
            model=effective_resolved.model_size,
            device=effective_resolved.device,
            chunks=len(chunk_plans),
            cache_hits=cache_hits,
            worker_count=worker_count,
            segments=len(ordered_segments),
            chunk_extract_seconds=f"{stage_metrics.get('chunk_extraction', 0.0):.3f}",
            chunk_transcribe_seconds=f"{stage_metrics.get('per_chunk_transcription', 0.0):.3f}",
        )
        return document
    except WhisperModelLoadError:
        project = load_project(project_id)
        project.discovery_transcription_status = ProcessingStatus.FAILED
        save_project(project)
        raise
    except Exception as exc:
        project = load_project(project_id)
        project.discovery_transcription_status = ProcessingStatus.FAILED
        save_project(project)
        if isinstance(exc, TranscriptionProcessError):
            raise
        raise TranscriptionProcessError(str(exc)) from exc
    finally:
        cleanup_temp_audio(temp_dir)


def retry_failed_discovery_chunks(project_id: str) -> TranscriptDocument:
    state = load_chunk_state(project_id)
    if state is None:
        raise TranscriptionProcessError("No discovery chunk state found.")
    for entry in state.chunks:
        if entry.status == ChunkProcessingStatus.FAILED:
            entry.status = ChunkProcessingStatus.PENDING
            entry.error = None
    save_chunk_state(project_id, state)
    return run_discovery_transcription(project_id)


def benchmark_discovery_transcription(
    project_id: str,
    *,
    language: str | None = "en",
    use_cache: bool = False,
) -> DiscoveryBenchmarkReport:
    """Run discovery transcription with stage timing enabled."""
    from app.services.transcription import locate_project_audio
    from app.services.video_processing import inspect_video_file

    audio_path = locate_project_audio(project_id)
    audio_duration = float(inspect_video_file(audio_path).duration_seconds or 0.0)
    settings_snapshot = resolve_discovery_settings(language=language)
    collector = DiscoveryTimingCollector(enabled=True)
    run_discovery_transcription(
        project_id,
        language=language,
        use_cache=use_cache,
        timing_collector=collector,
    )
    chunk_plans = plan_audio_chunks(duration=audio_duration)
    cache_hits = sum(
        1
        for record in collector._records
        if record.stage == "chunk_transcription"
    ) if use_cache else 0
    return collector.build_report(
        project_id=project_id,
        audio_duration_seconds=audio_duration,
        model=settings_snapshot.model_size,
        device=settings_snapshot.device,
        chunk_count=len(chunk_plans),
        cache_hits=cache_hits,
    )
