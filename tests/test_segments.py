"""Paragraflandirma, halusinasyon filtresi ve pencere dikisi."""

from __future__ import annotations

from helpers import seg

from palaskript.datatypes import Segment
from palaskript.segments import (
    TranscriptAssembler,
    build_paragraphs,
    ends_sentence,
    filter_hallucinations,
    merge_paragraphs,
    normalize,
)


class TestNormalize:
    def test_strips_punctuation_and_case(self):
        assert normalize("Merhaba, Dunya!") == normalize("merhaba dunya")

    def test_collapses_whitespace(self):
        assert normalize("bir   iki\n uc") == "bir iki uc"


class TestEndsSentence:
    def test_detects_terminators(self):
        assert ends_sentence("Bitti.")
        assert ends_sentence("Oyle mi?")
        assert ends_sentence("Su sekilde:")

    def test_rejects_mid_sentence(self):
        assert not ends_sentence("ve sonra")


class TestMergeParagraphs:
    def test_merges_short_fragments_into_one_paragraph(self):
        """Ham segmentler 5-10 saniyelik parcalar. Birlestirilmezse PDF okunmaz."""
        segments = [
            seg(0.0, 3.0, "Bugun sizinle"),
            seg(3.1, 6.0, "bir konuyu"),
            seg(6.1, 9.0, "konusacagiz"),
        ]
        paragraphs = merge_paragraphs(segments)
        assert len(paragraphs) == 1
        assert paragraphs[0].text == "Bugun sizinle bir konuyu konusacagiz"
        assert paragraphs[0].start == 0.0
        assert paragraphs[0].end == 9.0

    def test_breaks_on_sentence_end_plus_pause(self):
        segments = [
            seg(0.0, 3.0, "Ilk konu bitti."),
            seg(5.0, 8.0, "Ikinci konuya geciyoruz"),
        ]
        assert len(merge_paragraphs(segments)) == 2

    def test_does_not_break_on_pause_without_sentence_end(self):
        # 1.5-3.0 sn arasi duraklama, cumle bitmemis: bolmemeli.
        segments = [
            seg(0.0, 3.0, "Bu cumle devam"),
            seg(5.0, 8.0, "ediyor iste"),
        ]
        assert len(merge_paragraphs(segments)) == 1

    def test_breaks_on_long_pause_even_mid_sentence(self):
        segments = [
            seg(0.0, 3.0, "Yarim kalan bir"),
            seg(10.0, 13.0, "cumle vardi"),
        ]
        assert len(merge_paragraphs(segments)) == 2

    def test_hard_max_forces_break_in_continuous_speech(self):
        """Duraklamasiz konusmada paragraf sonsuza kadar uzamamali."""
        segments = [seg(i * 5.0, i * 5.0 + 4.9, "kelime") for i in range(40)]
        paragraphs = merge_paragraphs(segments, hard_max_seconds=90.0)
        assert len(paragraphs) > 1
        assert all((p.end - p.start) <= 100.0 for p in paragraphs)

    def test_soft_max_prefers_sentence_boundary(self):
        segments = [seg(i * 10.0, i * 10.0 + 9.0, "Bir cumle.") for i in range(10)]
        paragraphs = merge_paragraphs(segments, soft_max_seconds=40.0)
        assert len(paragraphs) > 1
        for para in paragraphs:
            assert para.text.endswith(".")

    def test_skips_empty_segments(self):
        segments = [seg(0.0, 1.0, "  "), seg(1.0, 2.0, "gecerli")]
        paragraphs = merge_paragraphs(segments)
        assert len(paragraphs) == 1
        assert paragraphs[0].text == "gecerli"

    def test_empty_input(self):
        assert merge_paragraphs([]) == []


class TestHallucinationFilter:
    def test_drops_runaway_repetition(self):
        """Whisper uzun kayitlarda ayni cumleyi dakikalarca tekrarlayabiliyor."""
        segments = [seg(i * 2.0, i * 2.0 + 1.9, "Altyazi M.K.") for i in range(20)]
        filtered = filter_hallucinations(segments, max_consecutive=2)
        assert len(filtered) == 2

    def test_extends_last_kept_segment_to_cover_dropped_time(self):
        segments = [seg(i * 2.0, i * 2.0 + 1.9, "tekrar") for i in range(10)]
        filtered = filter_hallucinations(segments, max_consecutive=2)
        assert filtered[-1].end == segments[-1].end

    def test_keeps_genuine_short_repetition(self):
        # Konusmaci gercekten iki kez soyleyebilir, bunu kesmiyoruz.
        segments = [seg(0.0, 1.0, "Evet"), seg(1.0, 2.0, "Evet"), seg(2.0, 3.0, "devam")]
        assert len(filter_hallucinations(segments, max_consecutive=2)) == 3

    def test_collapses_repetition_inside_one_segment(self):
        segments = [seg(0.0, 5.0, "Abone olun Abone olun Abone olun Abone olun")]
        assert filter_hallucinations(segments)[0].text == "Abone olun"

    def test_leaves_normal_text_untouched(self):
        text = "Bu normal bir cumle ve tekrar icermiyor"
        assert filter_hallucinations([seg(0.0, 3.0, text)])[0].text == text

    def test_different_texts_are_all_kept(self):
        segments = [seg(i, i + 0.9, f"cumle {i}") for i in range(5)]
        assert len(filter_hallucinations(segments)) == 5


class TestAssemblerSeam:
    def test_non_overlapped_windows_pass_through(self):
        assembler = TranscriptAssembler()
        assembler.add_window([seg(0.0, 5.0, "birinci")], overlapped=False)
        accepted = assembler.add_window([seg(5.0, 10.0, "ikinci")], overlapped=False)
        assert len(accepted) == 1
        assert len(assembler.result()) == 2

    def test_overlapped_window_drops_duplicated_text(self):
        """Sessizlik bulunamayinca 5 sn bindirme uygulaniyor; o bolge iki kez
        yaziliyor ve tekrar burada atilmali."""
        assembler = TranscriptAssembler()
        assembler.add_window(
            [seg(0.0, 5.0, "birinci cumle"), seg(5.0, 10.0, "ikinci cumle")],
            overlapped=False,
        )
        accepted = assembler.add_window(
            [seg(5.0, 10.0, "ikinci cumle"), seg(10.0, 15.0, "ucuncu cumle")],
            overlapped=True,
        )
        assert [s.text for s in accepted] == ["ucuncu cumle"]
        assert [s.text for s in assembler.result()] == [
            "birinci cumle",
            "ikinci cumle",
            "ucuncu cumle",
        ]

    def test_overlapped_window_keeps_new_text_at_same_time(self):
        # Bindirme bolgesinde yeni bir metin cikarsa (Whisper farkli duydu)
        # ve zaman araligini asiyorsa korunmali.
        assembler = TranscriptAssembler()
        assembler.add_window([seg(0.0, 10.0, "onceki")], overlapped=False)
        accepted = assembler.add_window(
            [seg(8.0, 14.0, "tamamen farkli bir metin")], overlapped=True
        )
        assert len(accepted) == 1

    def test_first_window_is_never_treated_as_overlapped(self):
        assembler = TranscriptAssembler()
        accepted = assembler.add_window([seg(0.0, 5.0, "ilk")], overlapped=True)
        assert len(accepted) == 1

    def test_empty_window_returns_nothing(self):
        assembler = TranscriptAssembler()
        assert assembler.add_window([], overlapped=False) == []

    def test_returned_segments_are_what_gets_checkpointed(self):
        """Kabul edilenler ara kayda yaziliyor; reddedilenler diske gitmemeli."""
        assembler = TranscriptAssembler()
        assembler.add_window([seg(0.0, 10.0, "ayni metin")], overlapped=False)
        accepted = assembler.add_window([seg(5.0, 10.0, "ayni metin")], overlapped=True)
        assert accepted == []


class TestBuildParagraphs:
    def test_filters_then_merges(self):
        segments = [
            seg(0.0, 3.0, "Gercek icerik."),
            *[seg(4.0 + i * 2, 5.9 + i * 2, "tekrar") for i in range(10)],
        ]
        paragraphs = build_paragraphs(segments)
        joined = " ".join(p.text for p in paragraphs)
        assert "Gercek icerik." in joined
        assert joined.count("tekrar") <= 2

    def test_handles_empty(self):
        assert build_paragraphs([]) == []


class TestSegmentSerialization:
    def test_round_trip(self):
        original = Segment(start=1.5, end=4.25, text="merhaba", language="tr")
        assert Segment.from_dict(original.to_dict()) == original
