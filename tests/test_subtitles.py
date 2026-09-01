"""Altyazi ayristirici.

Insan eliyle yazilmis altyazi 3 saatlik islemi 2 saniyeye indiriyor, bu yuzden
ayristiricinin YouTube'un gercek cikti bicimlerini dogru ele almasi onemli.
"""

from __future__ import annotations

from transkript.source import subtitles

VTT = """WEBVTT
Kind: captions
Language: tr

00:00:01.000 --> 00:00:04.000
Merhaba, bugun sizinle

00:00:04.500 --> 00:00:08.000
onemli bir konuyu konusacagiz.
"""

SRT = """1
00:00:01,000 --> 00:00:04,000
Birinci satir

2
00:00:05,000 --> 00:00:09,000
Ikinci satir
"""


class TestVtt:
    def test_parses_cues(self):
        segments = subtitles.parse(VTT)
        assert len(segments) == 2
        assert segments[0].start == 1.0
        assert segments[0].end == 4.0
        assert segments[0].text == "Merhaba, bugun sizinle"

    def test_ignores_header_lines(self):
        assert all("WEBVTT" not in s.text for s in subtitles.parse(VTT))

    def test_handles_hours(self):
        text = "WEBVTT\n\n01:02:03.500 --> 01:02:07.000\nUzun video\n"
        segment = subtitles.parse(text)[0]
        assert segment.start == 3723.5

    def test_strips_inline_tags(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<c.yellow>Renkli</c> metin\n"
        assert subtitles.parse(text)[0].text == "Renkli metin"

    def test_decodes_entities(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nAli &amp; Veli &lt;bak&gt;\n"
        assert subtitles.parse(text)[0].text == "Ali & Veli <bak>"

    def test_joins_multiline_cue(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nBirinci satir\nikinci satir\n"
        assert subtitles.parse(text)[0].text == "Birinci satir ikinci satir"

    def test_strips_cue_settings(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000 align:start position:10%\nMetin\n"
        assert subtitles.parse(text)[0].text == "Metin"


class TestSrt:
    def test_parses_comma_separated_millis(self):
        segments = subtitles.parse(SRT)
        assert len(segments) == 2
        assert segments[0].start == 1.0
        assert segments[1].text == "Ikinci satir"


class TestDedupe:
    def test_collapses_identical_consecutive_cues(self):
        """YouTube altyazilarinda ayni cumle kayan pencere gibi tekrarlanabiliyor."""
        text = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\nAyni cumle\n\n"
            "00:00:03.000 --> 00:00:05.000\nAyni cumle\n"
        )
        segments = subtitles.parse(text)
        assert len(segments) == 1
        assert segments[0].end == 5.0

    def test_replaces_prefix_with_the_longer_line(self):
        text = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\nBu cumle uzun bir cumledir\n\n"
            "00:00:03.000 --> 00:00:05.000\nBu cumle uzun bir cumledir ve devam ediyor\n"
        )
        segments = subtitles.parse(text)
        assert len(segments) == 1
        assert segments[0].text.endswith("devam ediyor")

    def test_keeps_genuinely_different_lines(self):
        segments = subtitles.parse(SRT)
        assert len(segments) == 2


class TestEdgeCases:
    def test_empty_input(self):
        assert subtitles.parse("") == []

    def test_no_cues(self):
        assert subtitles.parse("WEBVTT\n\nSadece basliklar\n") == []

    def test_zero_length_cue_is_skipped(self):
        text = "WEBVTT\n\n00:00:03.000 --> 00:00:03.000\nSifir uzunluk\n"
        assert subtitles.parse(text) == []

    def test_blank_cue_body_is_skipped(self):
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n\n00:00:04.000 --> 00:00:06.000\nDolu\n"
        segments = subtitles.parse(text)
        assert len(segments) == 1
        assert segments[0].text == "Dolu"

    def test_parse_file(self, tmp_path):
        path = tmp_path / "altyazi.vtt"
        path.write_text(VTT, encoding="utf-8")
        assert len(subtitles.parse_file(path)) == 2
