"""Bolumleme.

Konusma videolari icin en buyuk okunabilirlik kazanci burada: 90 sayfalik duz
metin duvari yerine gezilebilir bir belge.
"""

from __future__ import annotations

import pytest

from palaskript.chapters import (
    assign_paragraphs,
    auto_chapters,
    build_chapters,
    format_timestamp,
    normalize_chapters,
)
from palaskript.datatypes import Chapter, Paragraph, SourceInfo


def para(start: float, end: float, text: str = "metin") -> Paragraph:
    return Paragraph(start=start, end=end, text=text)


def source(duration: float, chapters: list[Chapter] | None = None) -> SourceInfo:
    return SourceInfo(
        kind="youtube",
        source_id="youtube:abc",
        title="Test",
        duration=duration,
        chapters=chapters or [],
    )


class TestFormatTimestamp:
    def test_under_an_hour_omits_hours(self):
        assert format_timestamp(75) == "01:15"

    def test_over_an_hour_includes_hours(self):
        assert format_timestamp(3725) == "01:02:05"

    def test_always_hours_forces_long_form(self):
        assert format_timestamp(75, always_hours=True) == "00:01:15"

    def test_negative_clamps_to_zero(self):
        assert format_timestamp(-5) == "00:00"


class TestNormalizeChapters:
    def test_fills_end_times_from_next_start(self):
        raw = [
            Chapter(start=0.0, end=0.0, title="Giris"),
            Chapter(start=100.0, end=0.0, title="Gelisme"),
        ]
        result = normalize_chapters(raw, duration=300.0)
        assert result[0].end == 100.0
        assert result[1].end == 300.0

    def test_sorts_out_of_order_input(self):
        raw = [
            Chapter(start=100.0, end=200.0, title="Ikinci"),
            Chapter(start=0.0, end=100.0, title="Birinci"),
        ]
        result = normalize_chapters(raw, duration=200.0)
        assert [c.title for c in result] == ["Birinci", "Ikinci"]

    def test_drops_zero_length_chapters(self):
        raw = [
            Chapter(start=0.0, end=0.0, title="A"),
            Chapter(start=0.0, end=0.0, title="B"),
            Chapter(start=50.0, end=0.0, title="C"),
        ]
        result = normalize_chapters(raw, duration=100.0)
        assert all(c.end > c.start for c in result)

    def test_untitled_chapter_gets_a_name(self):
        result = normalize_chapters([Chapter(start=0.0, end=10.0, title="  ")], duration=10.0)
        assert result[0].title

    def test_empty_input(self):
        assert normalize_chapters([], duration=100.0) == []


class TestAutoChapters:
    def test_splits_long_video_by_interval(self):
        result = auto_chapters(3600.0, interval_minutes=15)
        assert len(result) == 4
        assert all(c.origin == "auto" for c in result)

    def test_short_video_gets_no_chapters(self):
        assert auto_chapters(300.0, interval_minutes=15) == []

    def test_last_chapter_is_clamped_to_duration(self):
        result = auto_chapters(2000.0, interval_minutes=15)
        assert result[-1].end == 2000.0

    def test_titles_show_the_time_range(self):
        result = auto_chapters(3600.0, interval_minutes=30)
        assert "00:00:00" in result[0].title


class TestBuildChapters:
    def test_prefers_youtube_chapters(self):
        info = source(3600.0, [Chapter(start=0.0, end=1800.0, title="Acilis")])
        result = build_chapters(info, auto_interval_minutes=15)
        assert result[0].title == "Acilis"
        assert result[0].origin == "youtube"

    def test_falls_back_to_time_based(self):
        result = build_chapters(source(3600.0), auto_interval_minutes=15)
        assert result
        assert all(c.origin == "auto" for c in result)

    def test_disabled_returns_nothing(self):
        info = source(3600.0, [Chapter(start=0.0, end=1800.0, title="Acilis")])
        assert build_chapters(info, enabled=False) == []


class TestAssignParagraphs:
    def test_groups_paragraphs_under_their_chapter(self):
        chapters = [
            Chapter(start=0.0, end=100.0, title="Bir"),
            Chapter(start=100.0, end=200.0, title="Iki"),
        ]
        paragraphs = [para(10, 20), para(50, 60), para(110, 120)]
        groups = assign_paragraphs(paragraphs, chapters)
        assert [c.title for c, _ in groups] == ["Bir", "Iki"]
        assert len(groups[0][1]) == 2
        assert len(groups[1][1]) == 1

    def test_no_chapters_returns_single_flat_group(self):
        paragraphs = [para(0, 10), para(10, 20)]
        groups = assign_paragraphs(paragraphs, [])
        assert len(groups) == 1
        assert groups[0][0] is None
        assert groups[0][1] == paragraphs

    def test_content_before_first_chapter_is_not_lost(self):
        """Ilk bolum 0'dan sonra basliyorsa onundeki konusma kaybolmamali."""
        chapters = [Chapter(start=60.0, end=200.0, title="Asil konu")]
        paragraphs = [para(5, 15, "giris sozleri"), para(70, 80, "asil")]
        groups = assign_paragraphs(paragraphs, chapters)
        assert groups[0][0] is None
        assert groups[0][1][0].text == "giris sozleri"
        assert groups[1][0].title == "Asil konu"

    def test_empty_chapters_are_omitted(self):
        chapters = [
            Chapter(start=0.0, end=100.0, title="Dolu"),
            Chapter(start=100.0, end=200.0, title="Bos"),
        ]
        groups = assign_paragraphs([para(10, 20)], chapters)
        assert [c.title for c, _ in groups] == ["Dolu"]

    def test_every_paragraph_lands_somewhere(self):
        chapters = [Chapter(start=0.0, end=50.0, title="A"), Chapter(start=50.0, end=100.0, title="B")]
        paragraphs = [para(i * 5.0, i * 5.0 + 4.0) for i in range(20)]
        groups = assign_paragraphs(paragraphs, chapters)
        assigned = sum(len(items) for _, items in groups)
        assert assigned == len(paragraphs)

    def test_no_paragraphs(self):
        chapters = [Chapter(start=0.0, end=100.0, title="A")]
        assert assign_paragraphs([], chapters) == []


@pytest.mark.parametrize("interval", [5, 15, 30])
def test_auto_chapters_cover_full_duration(interval: int):
    duration = 7200.0
    chapters = auto_chapters(duration, interval_minutes=interval)
    assert chapters[0].start == 0.0
    assert chapters[-1].end == duration
    for previous, current in zip(chapters, chapters[1:], strict=False):
        assert current.start == previous.end
