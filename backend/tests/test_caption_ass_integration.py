from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.models.project import CaptionSegment, CaptionStyle, CaptionWord, CaptionWordsPerGroup
from app.services.caption_ass import build_ass_subtitles, parse_ass_dialogue_events
from app.services.video_processing import resolve_ffmpeg_executables


def _completed_process(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def _three_word_segment() -> CaptionSegment:
    return CaptionSegment(
        id="seg-render",
        text="one two three",
        start=0.0,
        end=3.0,
        words=[
            CaptionWord(word="one", start=0.2, end=0.8),
            CaptionWord(word="two", start=1.2, end=1.8),
            CaptionWord(word="three", start=2.2, end=2.8),
        ],
        sequence=0,
    )


def test_render_integration_ass_structure_for_three_words():
    style = CaptionStyle(
        words_per_group=CaptionWordsPerGroup.ONE,
        text_color="#CCCCCC",
        active_word_color="#00FF88",
    )
    ass = build_ass_subtitles([_three_word_segment()], style)
    events = parse_ass_dialogue_events(ass)

    assert len(events) == 3
    assert events[0].start_seconds == pytest.approx(0.2)
    assert events[0].end_seconds == pytest.approx(0.8)
    assert events[1].start_seconds == pytest.approx(1.2)
    assert events[2].start_seconds == pytest.approx(2.2)

    assert not any(
        event.start_seconds <= 0.9 < event.end_seconds for event in events
    ), "gap before word two should have no caption"
    assert not any(
        event.start_seconds <= 2.0 < event.end_seconds for event in events
    ), "gap before word three should have no caption"


def test_render_integration_burns_three_word_ass_with_audio_copy():
    try:
        ffmpeg, _ = resolve_ffmpeg_executables()
    except Exception:
        pytest.skip("FFmpeg not available")

    style = CaptionStyle(words_per_group=CaptionWordsPerGroup.ONE)
    ass_content = build_ass_subtitles([_three_word_segment()], style)

    with tempfile.TemporaryDirectory(prefix="caption-ass-int-") as temp_dir:
        work_dir = Path(temp_dir)
        source_path = work_dir / "source.mp4"
        ass_path = work_dir / "captions.part.ass"
        output_path = work_dir / "captioned.part.mp4"

        generate = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=640x360:d=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=3",
                "-shortest",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-y",
                str(source_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if generate.returncode != 0:
            pytest.skip(f"Unable to generate test video: {generate.stderr}")

        ass_path.write_text(ass_content, encoding="utf-8")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "source.mp4",
            "-vf",
            "ass=captions.part.ass",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-y",
            "captioned.part.mp4",
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(work_dir),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        probe = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-i",
                str(output_path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "Audio:" in probe.stderr

        events = parse_ass_dialogue_events(ass_content)
        assert _event_active(events, 0.1) is None
        assert _event_active(events, 0.5) == "one"
        assert _event_active(events, 1.0) is None
        assert _event_active(events, 1.5) == "two"
        assert _event_active(events, 2.5) == "three"


def _event_active(events, current_time: float) -> str | None:
    for event in events:
        if event.start_seconds <= current_time < event.end_seconds:
            if "one" in event.text:
                return "one"
            if "two" in event.text:
                return "two"
            if "three" in event.text:
                return "three"
    return None
