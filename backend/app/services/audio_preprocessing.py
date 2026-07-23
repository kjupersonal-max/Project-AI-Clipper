from __future__ import annotations

import logging
import shutil
import struct
import wave
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.core.config import settings
from app.services.video_processing import _get_ffmpeg_path, _run_command, ensure_ffmpeg_tools

logger = logging.getLogger(__name__)


class PreprocessingMode(str, Enum):
    ORIGINAL = "original"
    NORMALIZED = "normalized"
    SPEECH_FILTERED = "speech_filtered"


class ChannelMixMode(str, Enum):
    MONO = "mono"
    LEFT = "left"
    RIGHT = "right"
    NORMALIZED_DOWNMIX = "normalized_downmix"


class AudioPreprocessingError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class AudioProperties:
    path: Path
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    size_bytes: int
    peak_amplitude: float | None = None
    rms_level: float | None = None


@dataclass
class ChannelLevelDiagnostics:
    channel: str
    peak_amplitude: float
    rms_level: float


@dataclass
class PreprocessingResult:
    output_path: Path
    source: AudioProperties
    output: AudioProperties
    command: list[str]
    mode: PreprocessingMode
    channel_mix: ChannelMixMode
    warnings: list[str]
    used_fallback: bool = False


def _probe_wav_levels(wav_path: Path) -> tuple[float, float]:
    with wave.open(str(wav_path), "rb") as handle:
        sample_width = handle.getsampwidth()
        if sample_width != 2:
            return 0.0, 0.0
        frames = handle.readframes(handle.getnframes())
    if not frames:
        return 0.0, 0.0
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 / 32768.0
    return round(peak, 6), round(rms, 6)


def _probe_audio_properties(
    audio_path: Path,
    *,
    channel_mix: ChannelMixMode = ChannelMixMode.MONO,
) -> AudioProperties:
    from app.services.video_processing import inspect_video_file

    metadata = inspect_video_file(audio_path)
    peak, rms = _probe_wav_levels(audio_path) if audio_path.suffix.lower() == ".wav" else (None, None)
    return AudioProperties(
        path=audio_path,
        duration_seconds=metadata.duration_seconds,
        sample_rate=metadata.sample_rate,
        channels=metadata.audio_channels,
        size_bytes=audio_path.stat().st_size if audio_path.exists() else 0,
        peak_amplitude=peak,
        rms_level=rms,
    )


def analyze_channel_levels(source_path: Path) -> list[ChannelLevelDiagnostics]:
    ensure_ffmpeg_tools()
    temp_dir = source_path.parent / "_channel_diag"
    temp_dir.mkdir(parents=True, exist_ok=True)
    diagnostics: list[ChannelLevelDiagnostics] = []

    for mix in ChannelMixMode:
        output_path = temp_dir / f"{mix.value}.wav"
        try:
            prepare_audio_variant(
                source_path,
                output_path=output_path,
                mode=PreprocessingMode.ORIGINAL,
                channel_mix=mix,
            )
            peak, rms = _probe_wav_levels(output_path)
            diagnostics.append(
                ChannelLevelDiagnostics(channel=mix.value, peak_amplitude=peak, rms_level=rms)
            )
        except AudioPreprocessingError:
            continue
        finally:
            output_path.unlink(missing_ok=True)

    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    return diagnostics


def _channel_filter(channel_mix: ChannelMixMode) -> str | None:
    if channel_mix == ChannelMixMode.LEFT:
        return "pan=mono|c0=c0"
    if channel_mix == ChannelMixMode.RIGHT:
        return "pan=mono|c0=c1"
    if channel_mix == ChannelMixMode.NORMALIZED_DOWNMIX:
        return "pan=mono|c0=0.5*c0+0.5*c1"
    return None


def _mode_filter(mode: PreprocessingMode) -> str | None:
    if mode == PreprocessingMode.ORIGINAL:
        return None
    if mode == PreprocessingMode.NORMALIZED:
        return "loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95"
    return "highpass=f=80,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95"


def _build_preprocessing_command(
    source_path: Path,
    output_path: Path,
    *,
    mode: PreprocessingMode,
    channel_mix: ChannelMixMode = ChannelMixMode.MONO,
) -> list[str]:
    filters: list[str] = []
    channel_filter = _channel_filter(channel_mix)
    mode_filter = _mode_filter(mode)
    if channel_filter:
        filters.append(channel_filter)
    if mode_filter:
        filters.append(mode_filter)

    command = [
        _get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    if filters:
        command.extend(["-af", ",".join(filters)])
    command.extend(["-c:a", "pcm_s16le", "-y", str(output_path)])
    return command


def prepare_audio_variant(
    source_path: Path,
    *,
    output_path: Path,
    mode: PreprocessingMode,
    channel_mix: ChannelMixMode = ChannelMixMode.MONO,
) -> PreprocessingResult:
    ensure_ffmpeg_tools()
    source = _probe_audio_properties(source_path, channel_mix=channel_mix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(".part.wav")
    if temp_output.exists():
        temp_output.unlink()

    if mode == PreprocessingMode.ORIGINAL and channel_mix == ChannelMixMode.MONO:
        if (
            source_path.suffix.lower() == ".wav"
            and source.sample_rate == 16000
            and (source.channels or 1) == 1
            and source_path.resolve() != output_path.resolve()
        ):
            shutil.copy2(source_path, temp_output)
            temp_output.replace(output_path)
            output = _probe_audio_properties(output_path, channel_mix=channel_mix)
            return PreprocessingResult(
                output_path=output_path,
                source=source,
                output=output,
                command=["copy", str(source_path), str(output_path)],
                mode=mode,
                channel_mix=channel_mix,
                warnings=[],
            )

    command = _build_preprocessing_command(
        source_path,
        temp_output,
        mode=mode,
        channel_mix=channel_mix,
    )
    logger.info("Audio preprocessing (%s/%s): %s", mode.value, channel_mix.value, " ".join(command))

    result = _run_command(command, timeout_seconds=settings.ffmpeg_timeout_seconds)
    if result.returncode != 0:
        raise AudioPreprocessingError(result.stderr.strip() or "Preprocessing failed.")
    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise AudioPreprocessingError("Preprocessing produced an empty output file.")

    if output_path.exists():
        output_path.unlink()
    temp_output.replace(output_path)
    output = _probe_audio_properties(output_path, channel_mix=channel_mix)
    return PreprocessingResult(
        output_path=output_path,
        source=source,
        output=output,
        command=command,
        mode=mode,
        channel_mix=channel_mix,
        warnings=[],
    )


def prepare_audio_for_transcription(
    source_path: Path,
    *,
    temp_dir: Path,
    mode: PreprocessingMode = PreprocessingMode.ORIGINAL,
    channel_mix: ChannelMixMode = ChannelMixMode.MONO,
) -> tuple[Path, list[str], bool]:
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = temp_dir / f"{source_path.stem}.{mode.value}.{channel_mix.value}.wav"
    try:
        result = prepare_audio_variant(
            source_path,
            output_path=output_path,
            mode=mode,
            channel_mix=channel_mix,
        )
        return result.output_path, result.warnings, False
    except AudioPreprocessingError as exc:
        logger.warning(
            "Audio preprocessing failed (%s/%s), using original audio: %s",
            mode.value,
            channel_mix.value,
            exc.message,
        )
        return source_path, [f"Preprocessing failed; using original audio. {exc.message}"], True


def preprocess_with_fallback(
    source_path: Path,
    *,
    temp_dir: Path,
    mode: PreprocessingMode = PreprocessingMode.ORIGINAL,
) -> tuple[Path, list[str], bool]:
    return prepare_audio_for_transcription(source_path, temp_dir=temp_dir, mode=mode)


def cleanup_temp_audio(path: Path) -> None:
    if not path.exists():
        return
    if path.suffix == ".wav" and any(
        marker in path.stem for marker in (".original.", ".normalized.", ".speech_filtered.", ".preprocessed")
    ):
        path.unlink(missing_ok=True)
        return
    parent = path.parent
    if parent.name.startswith(("transcribe_", "_transcribe_temp", "_diag")) and parent.exists():
        shutil.rmtree(parent, ignore_errors=True)
