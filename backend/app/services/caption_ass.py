from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.config import settings
from app.models.project import (
    CaptionAnimationType,
    CaptionSegment,
    CaptionStyle,
    CaptionTextAlignment,
    CaptionTextTransform,
    CaptionWord,
    CaptionWordsPerGroup,
)

logger = logging.getLogger(__name__)

# Shared with frontend caption-style.ts — keep values in sync.
CAPTION_FONT_ASS_MAP: dict[str, str] = {
    "Inter, system-ui, sans-serif": "Arial",
    "Arial, Helvetica, sans-serif": "Arial",
    "Georgia, serif": "Georgia",
    "Impact, Haettenschweiler, sans-serif": "Impact",
    "Courier New, monospace": "Courier New",
    "Verdana, Geneva, sans-serif": "Verdana",
}

DEFAULT_ASS_FONT = "Arial"
DEFAULT_PLAY_RES_X = 1920
DEFAULT_PLAY_RES_Y = 1080

_DIALOGUE_LINE = re.compile(
    r"^Dialogue:\s*\d+,([^,]+),([^,]+),Default,,0,0,0,,(.*)$"
)


@dataclass(frozen=True)
class CaptionWordGroup:
    words: list[CaptionWord]
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class AssDialogueEvent:
    start: str
    end: str
    text: str
    start_seconds: float
    end_seconds: float


def resolve_ass_font(font_family: str) -> str:
    normalized = font_family.strip()
    if normalized in CAPTION_FONT_ASS_MAP:
        return CAPTION_FONT_ASS_MAP[normalized]
    first = normalized.split(",")[0].strip().strip('"').strip("'")
    return first or DEFAULT_ASS_FONT


def apply_text_transform(text: str, transform: CaptionTextTransform) -> str:
    if transform == CaptionTextTransform.UPPERCASE:
        return text.upper()
    if transform == CaptionTextTransform.LOWERCASE:
        return text.lower()
    return text


def group_caption_words(
    segment: CaptionSegment,
    words_per_group: CaptionWordsPerGroup,
) -> list[CaptionWordGroup]:
    if words_per_group == CaptionWordsPerGroup.FULL or not segment.words:
        return [
            CaptionWordGroup(
                words=list(segment.words),
                text=segment.text,
                start=segment.start,
                end=segment.end,
            )
        ]

    chunk_size = int(words_per_group.value)
    groups: list[CaptionWordGroup] = []

    for index in range(0, len(segment.words), chunk_size):
        words = segment.words[index : index + chunk_size]
        groups.append(
            CaptionWordGroup(
                words=words,
                text=" ".join(word.word for word in words),
                start=words[0].start,
                end=words[-1].end,
            )
        )

    return groups or [
        CaptionWordGroup(
            words=[],
            text=segment.text,
            start=segment.start,
            end=segment.end,
        )
    ]


def _hex_to_ass_color(hex_color: str, *, alpha: int = 0) -> str:
    normalized = hex_color.lstrip("#")
    if len(normalized) != 6:
        return f"&H{alpha:02X}000000"

    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    return f"&H{alpha:02X}{blue:02X}{green:02X}{red:02X}"


def _seconds_to_ass_time(seconds: float) -> str:
    safe = max(0.0, seconds)
    hours = int(safe // 3600)
    minutes = int((safe % 3600) // 60)
    secs = safe % 60
    whole = int(secs)
    centiseconds = int(round((secs - whole) * 100))
    if centiseconds >= 100:
        whole += 1
        centiseconds = 0
    if whole >= 60:
        minutes += whole // 60
        whole = whole % 60
    if minutes >= 60:
        hours += minutes // 60
        minutes = minutes % 60
    return f"{hours}:{minutes:02d}:{whole:02d}.{centiseconds:02d}"


def ass_time_to_seconds(timestamp: str) -> float:
    hours, minutes, remainder = timestamp.split(":")
    whole, centiseconds = remainder.split(".")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(whole)
        + int(centiseconds) / 100.0
    )


def parse_ass_dialogue_events(ass_content: str) -> list[AssDialogueEvent]:
    events: list[AssDialogueEvent] = []
    for line in ass_content.splitlines():
        match = _DIALOGUE_LINE.match(line.strip())
        if not match:
            continue
        start, end, text = match.groups()
        events.append(
            AssDialogueEvent(
                start=start,
                end=end,
                text=text,
                start_seconds=ass_time_to_seconds(start),
                end_seconds=ass_time_to_seconds(end),
            )
        )
    return events


def _event_end_seconds(start: float, end: float) -> float:
    if end <= start:
        return start + 0.01
    return end


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _ass_alignment(text_alignment: CaptionTextAlignment) -> int:
    if text_alignment == CaptionTextAlignment.LEFT:
        return 1
    if text_alignment == CaptionTextAlignment.RIGHT:
        return 3
    return 2


def _scale_font_size(font_size: float, play_res_y: int) -> int:
    # Preview font sizes target a ~360px-tall player; scale to output resolution.
    scaled = font_size * (play_res_y / 360.0)
    return max(12, min(int(round(scaled)), 120))


def _position_tags(
    style: CaptionStyle,
    play_res_x: int,
    play_res_y: int,
) -> str:
    x = int(round(style.horizontal_position / 100.0 * play_res_x))
    y = int(round(style.vertical_position / 100.0 * play_res_y))
    return f"\\pos({x},{y})"


def _wrap_width_tag(style: CaptionStyle, play_res_x: int) -> str:
    return "\\q2\\fsp0"


def _animation_tags(style: CaptionStyle, play_res_x: int, play_res_y: int) -> str:
    intensity = max(0.0, min(style.animation_intensity, 1.0))
    if style.animation_type == CaptionAnimationType.NONE:
        return ""

    fade_ms = int(150 + intensity * 450)
    transform_ms = int(180 + intensity * 420)
    x = int(round(style.horizontal_position / 100.0 * play_res_x))
    y = int(round(style.vertical_position / 100.0 * play_res_y))

    if style.animation_type == CaptionAnimationType.FADE:
        return f"\\fad({fade_ms},{int(fade_ms * 0.6)})"

    if style.animation_type in {CaptionAnimationType.POP, CaptionAnimationType.SCALE}:
        peak = int(100 + intensity * (15 if style.animation_type == CaptionAnimationType.POP else 25))
        return (
            f"\\fscx{peak}\\fscy{peak}"
            f"\\t(0,{transform_ms},\\fscx100\\fscy100)"
        )

    if style.animation_type == CaptionAnimationType.SLIDE_UP:
        offset = int(12 + intensity * 36)
        return f"\\move({x},{y + offset},{x},{y},0,{transform_ms})"

    if style.animation_type == CaptionAnimationType.BOUNCE:
        lift = int(8 + intensity * 18)
        half = max(80, transform_ms // 2)
        return (
            f"\\move({x},{y + lift},{x},{y - lift},0,{half})"
            f"\\t({half},{transform_ms},\\frz0)"
            f"\\move({x},{y - lift},{x},{y},{half},{transform_ms})"
        )

    if style.animation_type == CaptionAnimationType.ACTIVE_WORD_EMPHASIS:
        return ""

    return ""


def _word_highlight_text(
    group: CaptionWordGroup,
    style: CaptionStyle,
    *,
    words_per_group: CaptionWordsPerGroup,
) -> str:
    text_ass = _hex_to_ass_color(style.text_color)
    active_ass = _hex_to_ass_color(style.active_word_color)
    group_start = group.start

    parts: list[str] = []
    for index, word in enumerate(group.words):
        text = _escape_ass_text(apply_text_transform(word.word, style.text_transform))
        if words_per_group == CaptionWordsPerGroup.ONE:
            parts.append(f"{{\\1c{active_ass}}}{text}")
            continue

        rel_start_ms = max(0, int(round((word.start - group_start) * 1000)))
        rel_end_ms = max(rel_start_ms, int(round((word.end - group_start) * 1000)))
        parts.append(
            "{"
            + f"\\1c{text_ass}"
            + f"\\t({rel_start_ms},{rel_start_ms},\\1c{active_ass})"
            + f"\\t({rel_end_ms},{rel_end_ms},\\1c{text_ass})"
            + "}"
            + text
        )
        if index < len(group.words) - 1:
            parts.append(" ")

    return "".join(parts)


def _dialogue_text(
    group: CaptionWordGroup,
    style: CaptionStyle,
    play_res_x: int,
    play_res_y: int,
) -> str:
    prefix = (
        "{"
        + _position_tags(style, play_res_x, play_res_y)
        + _wrap_width_tag(style, play_res_x)
        + _animation_tags(style, play_res_x, play_res_y)
        + "}"
    )

    if group.words:
        return prefix + _word_highlight_text(
            group,
            style,
            words_per_group=style.words_per_group,
        )

    text = _escape_ass_text(apply_text_transform(group.text, style.text_transform))
    return prefix + text


def _log_ass_generation(
    *,
    style: CaptionStyle,
    groups: list[CaptionWordGroup],
    events: list[tuple[float, float, str]],
) -> None:
    if not settings.caption_ass_debug_logging:
        return

    logger.info(
        "ASS generation: words_per_group=%s text_color=%s active_word_color=%s",
        style.words_per_group.value,
        style.text_color,
        style.active_word_color,
    )
    for group in groups:
        logger.info(
            "ASS group text=%r start=%.3f end=%.3f",
            group.text,
            group.start,
            group.end,
        )
        for word in group.words:
            logger.info(
                "ASS word input %r start=%.3f end=%.3f",
                word.word,
                word.start,
                word.end,
            )
    for start, end, text in events:
        logger.info(
            "ASS event start=%s end=%s text=%r",
            _seconds_to_ass_time(start),
            _seconds_to_ass_time(end),
            text,
        )


def build_ass_subtitles(
    segments: list[CaptionSegment],
    style: CaptionStyle,
    *,
    play_res_x: int = DEFAULT_PLAY_RES_X,
    play_res_y: int = DEFAULT_PLAY_RES_Y,
) -> str:
    font_name = resolve_ass_font(style.font_family)
    font_size = _scale_font_size(style.font_size, play_res_y)
    bold = -1 if style.font_weight >= 600 else 0

    primary = _hex_to_ass_color(style.text_color)
    secondary = _hex_to_ass_color(style.active_word_color)
    outline = _hex_to_ass_color(style.outline_color)
    background_alpha = int(round((1.0 - style.background_opacity) * 255))
    background = _hex_to_ass_color(style.background_color, alpha=background_alpha)
    shadow_alpha = 0 if style.shadow_enabled else 255
    shadow = _hex_to_ass_color("#000000", alpha=shadow_alpha)
    outline_width = max(0.0, min(style.outline_width, 8.0))
    shadow_depth = int(round(style.shadow_strength * 4)) if style.shadow_enabled else 0
    alignment = _ass_alignment(style.text_alignment)
    border_style = 3 if style.background_opacity > 0.01 else 1

    header = [
        "[Script Info]",
        "Title: AI Clipper Captions",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            "Style: Default,"
            f"{font_name},{font_size},{primary},{secondary},{outline},{background},"
            f"{bold},0,0,0,100,100,0,0,{border_style},{outline_width:.1f},{shadow_depth},{alignment},"
            f"20,20,20,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    debug_events: list[tuple[float, float, str]] = []
    debug_groups: list[CaptionWordGroup] = []
    sorted_segments = sorted(segments, key=lambda segment: segment.sequence)

    for segment in sorted_segments:
        groups = group_caption_words(segment, style.words_per_group)
        debug_groups.extend(groups)
        for group in groups:
            if group.words:
                if style.words_per_group == CaptionWordsPerGroup.ONE:
                    for word in group.words:
                        start_seconds = word.start
                        end_seconds = _event_end_seconds(word.start, word.end)
                        text = _dialogue_text(
                            CaptionWordGroup(
                                words=[word],
                                text=word.word,
                                start=word.start,
                                end=word.end,
                            ),
                            style,
                            play_res_x,
                            play_res_y,
                        )
                        start = _seconds_to_ass_time(start_seconds)
                        end = _seconds_to_ass_time(end_seconds)
                        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
                        debug_events.append((start_seconds, end_seconds, text))
                    continue

                start_seconds = group.start
                end_seconds = _event_end_seconds(group.start, group.end)
            else:
                start_seconds = group.start
                end_seconds = _event_end_seconds(group.start, group.end)

            start = _seconds_to_ass_time(start_seconds)
            end = _seconds_to_ass_time(end_seconds)
            text = _dialogue_text(group, style, play_res_x, play_res_y)
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
            debug_events.append((start_seconds, end_seconds, text))

    _log_ass_generation(style=style, groups=debug_groups, events=debug_events)

    return "\n".join(header + events) + "\n"


def probe_play_resolution(width: int | None, height: int | None) -> tuple[int, int]:
    if width and height and width > 0 and height > 0:
        return width, height
    return DEFAULT_PLAY_RES_X, DEFAULT_PLAY_RES_Y
