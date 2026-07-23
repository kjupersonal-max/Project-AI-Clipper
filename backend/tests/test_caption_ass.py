from __future__ import annotations

from pathlib import Path

import pytest

from app.models.project import (
    CaptionAnimationType,
    CaptionSegment,
    CaptionStyle,
    CaptionStylePresetId,
    CaptionTextTransform,
    CaptionWord,
    CaptionWordsPerGroup,
)
from app.services.caption_ass import (
    CAPTION_FONT_ASS_MAP,
    ass_time_to_seconds,
    build_ass_subtitles,
    group_caption_words,
    parse_ass_dialogue_events,
    resolve_ass_font,
)


def _sample_style(**overrides) -> CaptionStyle:
    base = CaptionStyle()
    return base.model_copy(update=overrides)


def _word_segment(**overrides) -> CaptionSegment:
    defaults = {
        "id": "seg-1",
        "text": "Hello beautiful world",
        "start": 0.0,
        "end": 3.0,
        "words": [
            CaptionWord(word="Hello", start=0.0, end=0.8),
            CaptionWord(word="beautiful", start=0.8, end=1.6),
            CaptionWord(word="world", start=1.6, end=3.0),
        ],
        "sequence": 0,
    }
    defaults.update(overrides)
    return CaptionSegment(**defaults)


def _gapped_segment() -> CaptionSegment:
    return CaptionSegment(
        id="seg-gap",
        text="one two three",
        start=0.0,
        end=2.0,
        words=[
            CaptionWord(word="one", start=0.0, end=0.137),
            CaptionWord(word="two", start=0.891, end=1.2),
            CaptionWord(word="three", start=1.35, end=2.0),
        ],
        sequence=0,
    )


def _trimmed_segment() -> CaptionSegment:
    return CaptionSegment(
        id="seg-trim",
        text="alpha beta",
        start=0.0,
        end=1.5,
        words=[
            CaptionWord(word="alpha", start=0.0, end=0.5),
            CaptionWord(word="beta", start=0.75, end=1.5),
        ],
        sequence=0,
    )


def _events_active_at(events, current_time: float):
    return [
        event
        for event in events
        if event.start_seconds <= current_time < event.end_seconds
    ]


def test_resolve_ass_font_mapping():
    assert resolve_ass_font("Inter, system-ui, sans-serif") == "Arial"
    assert resolve_ass_font("Impact, Haettenschweiler, sans-serif") == "Impact"
    assert "Arial" in CAPTION_FONT_ASS_MAP.values()


def test_group_caption_words():
    segment = _word_segment()
    groups = group_caption_words(segment, CaptionWordsPerGroup.TWO)
    assert len(groups) == 2
    assert groups[0].text == "Hello beautiful"
    assert groups[0].start == 0.0
    assert groups[0].end == 1.6
    assert groups[1].text == "world"
    assert groups[1].start == 1.6
    assert groups[1].end == 3.0


def test_build_ass_uses_timed_color_tags_not_karaoke():
    ass = build_ass_subtitles(
        [_word_segment()],
        _sample_style(words_per_group=CaptionWordsPerGroup.TWO),
    )
    assert "\\k" not in ass
    assert "\\1c" in ass
    assert "\\t(" in ass
    assert "Hello" in ass


def test_build_ass_segment_fallback_without_words():
    segment = CaptionSegment(
        id="seg-2",
        text="Segment only",
        start=0.0,
        end=2.0,
        words=[],
        sequence=0,
    )
    ass = build_ass_subtitles([segment], _sample_style())
    events = parse_ass_dialogue_events(ass)
    assert len(events) == 1
    assert "Segment only" in events[0].text
    assert "\\k" not in ass
    assert events[0].start_seconds == 0.0
    assert events[0].end_seconds == 2.0


def test_build_ass_applies_text_transform():
    ass = build_ass_subtitles(
        [_word_segment()],
        _sample_style(text_transform=CaptionTextTransform.UPPERCASE),
    )
    assert "HELLO" in ass


def test_build_ass_includes_animation_tags():
    ass = build_ass_subtitles(
        [_word_segment()],
        _sample_style(
            animation_type=CaptionAnimationType.FADE,
            animation_intensity=0.8,
        ),
    )
    assert "\\fad(" in ass


def test_build_ass_style_primary_is_text_secondary_is_active():
    ass = build_ass_subtitles(
        [_word_segment()],
        _sample_style(
            preset_id=CaptionStylePresetId.BOLD_POP,
            text_color="#FF0000",
            active_word_color="#00FF00",
        ),
    )
    style_line = next(line for line in ass.splitlines() if line.startswith("Style: Default,"))
    assert "&H000000FF" in style_line
    assert "&H0000FF00" in style_line


def test_single_word_grouping_one_event_per_word():
    ass = build_ass_subtitles(
        [_gapped_segment()],
        _sample_style(
            text_color="#CCCCCC",
            active_word_color="#00FF88",
            words_per_group=CaptionWordsPerGroup.ONE,
        ),
    )
    events = parse_ass_dialogue_events(ass)
    assert len(events) == 3
    assert events[0].start_seconds == pytest.approx(0.0)
    assert events[0].end_seconds == pytest.approx(0.137, abs=0.01)
    assert events[1].start_seconds == pytest.approx(0.891, abs=0.01)
    assert events[1].end_seconds == pytest.approx(1.2)
    assert events[2].start_seconds == pytest.approx(1.35)
    assert events[2].end_seconds == pytest.approx(2.0)
    assert "one" in events[0].text
    assert "two" in events[1].text
    assert "three" in events[2].text
    assert "one" not in events[1].text
    assert "two" not in events[0].text


def test_single_word_grouping_uses_active_color_only():
    ass = build_ass_subtitles(
        [_word_segment(words=[CaptionWord(word="Hello", start=0.0, end=0.8)])],
        _sample_style(
            text_color="#CCCCCC",
            active_word_color="#00FF88",
            words_per_group=CaptionWordsPerGroup.ONE,
        ),
    )
    events = parse_ass_dialogue_events(ass)
    assert len(events) == 1
    assert "\\1c&H0088FF00" in events[0].text
    assert "\\k" not in events[0].text


def test_single_word_grouping_preserves_gaps():
    events = parse_ass_dialogue_events(
        build_ass_subtitles(
            [_gapped_segment()],
            _sample_style(words_per_group=CaptionWordsPerGroup.ONE),
        )
    )
    assert _events_active_at(events, 0.05)
    assert not _events_active_at(events, 0.5)
    assert _events_active_at(events, 1.0)
    assert not _events_active_at(events, 1.25)


def test_two_word_grouping_boundaries_and_color_tags():
    ass = build_ass_subtitles(
        [_word_segment()],
        _sample_style(
            text_color="#CCCCCC",
            active_word_color="#00FF88",
            words_per_group=CaptionWordsPerGroup.TWO,
        ),
    )
    events = parse_ass_dialogue_events(ass)
    assert len(events) == 2
    assert events[0].start_seconds == pytest.approx(0.0)
    assert events[0].end_seconds == pytest.approx(1.6)
    assert events[1].start_seconds == pytest.approx(1.6)
    assert events[1].end_seconds == pytest.approx(3.0)
    assert "Hello" in events[0].text and "beautiful" in events[0].text
    assert "\\t(0,0,\\1c&H0088FF00)" in events[0].text
    assert "\\t(800,800,\\1c&H0088FF00)" in events[0].text
    assert "\\t(800,800,\\1c&H00CCCCCC)" in events[0].text
    assert "\\t(1600,1600,\\1c&H00CCCCCC)" in events[0].text


def test_three_word_grouping_active_word_timing():
    segment = CaptionSegment(
        id="seg-3",
        text="alpha beta gamma",
        start=0.0,
        end=3.0,
        words=[
            CaptionWord(word="alpha", start=0.0, end=0.9),
            CaptionWord(word="beta", start=0.9, end=1.8),
            CaptionWord(word="gamma", start=1.8, end=3.0),
        ],
        sequence=0,
    )
    ass = build_ass_subtitles(
        [segment],
        _sample_style(
            text_color="#111111",
            active_word_color="#222222",
            words_per_group=CaptionWordsPerGroup.THREE,
        ),
    )
    events = parse_ass_dialogue_events(ass)
    assert len(events) == 1
    assert "\\t(0,0,\\1c&H00222222)" in events[0].text
    assert "\\t(900,900,\\1c&H00222222)" in events[0].text
    assert "\\t(900,900,\\1c&H00111111)" in events[0].text
    assert "\\t(1800,1800,\\1c&H00222222)" in events[0].text


def test_four_word_grouping():
    segment = CaptionSegment(
        id="seg-4",
        text="a b c d e",
        start=0.0,
        end=5.0,
        words=[
            CaptionWord(word="a", start=0.0, end=0.5),
            CaptionWord(word="b", start=0.5, end=1.0),
            CaptionWord(word="c", start=1.0, end=1.5),
            CaptionWord(word="d", start=1.5, end=2.0),
            CaptionWord(word="e", start=2.0, end=2.5),
        ],
        sequence=0,
    )
    events = parse_ass_dialogue_events(
        build_ass_subtitles(
            [segment],
            _sample_style(words_per_group=CaptionWordsPerGroup.FOUR),
        )
    )
    assert len(events) == 2
    assert events[0].end_seconds == pytest.approx(2.0)
    assert events[1].start_seconds == pytest.approx(2.0)


def test_fractional_word_timestamps():
    events = parse_ass_dialogue_events(
        build_ass_subtitles(
            [_gapped_segment()],
            _sample_style(words_per_group=CaptionWordsPerGroup.ONE),
        )
    )
    assert events[0].start == "0:00:00.00"
    assert events[0].end == "0:00:00.14"
    assert events[1].start == "0:00:00.89"
    assert ass_time_to_seconds(events[1].start) == pytest.approx(0.891, abs=0.01)


def test_trimmed_clip_word_timing_at_zero():
    events = parse_ass_dialogue_events(
        build_ass_subtitles(
            [_trimmed_segment()],
            _sample_style(words_per_group=CaptionWordsPerGroup.ONE),
        )
    )
    assert events[0].start_seconds == 0.0
    assert events[0].end_seconds == pytest.approx(0.5)
    assert events[1].start_seconds == pytest.approx(0.75)


def test_ass_time_roundtrip():
    assert ass_time_to_seconds("0:00:00.89") == pytest.approx(0.89, abs=0.001)
    assert ass_time_to_seconds("0:00:01.35") == pytest.approx(1.35, abs=0.001)


def test_three_word_timeline_visibility():
    events = parse_ass_dialogue_events(
        build_ass_subtitles(
            [_gapped_segment()],
            _sample_style(words_per_group=CaptionWordsPerGroup.ONE),
        )
    )
    assert not _events_active_at(events, 0.2)
    assert _events_active_at(events, 0.05)
    assert not _events_active_at(events, 0.5)
    assert _events_active_at(events, 1.0)
    assert _events_active_at(events, 1.5)
