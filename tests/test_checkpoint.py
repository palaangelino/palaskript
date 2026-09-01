"""Ara kayit ve devam ettirme.

Uzun isler buna bagli: 6 saatlik bir transkripsiyon cokme veya kapatma yuzunden
sifirdan baslamamali. Kritik kural: bir pencere ancak KENDI ISARETI yazildiginda
islenmis sayilir; yarim kalan pencerenin segmentleri atilir, cunku o pencere
bastan islenecek ve tutulsalardi metin iki kez cikardi.
"""

from __future__ import annotations

from helpers import seg

from transkript.checkpoint import Checkpoint, has_checkpoint
from transkript.datatypes import Segment


class TestRoundTrip:
    def test_committed_windows_are_restored(self, tmp_path):
        with Checkpoint("job1", tmp_path) as ck:
            ck.write_segments([seg(0.0, 5.0, "bir"), seg(5.0, 10.0, "iki")])
            ck.commit_window(0, 10.0)

        segments, resume_at, _ = Checkpoint("job1", tmp_path).load()
        assert [s.text for s in segments] == ["bir", "iki"]
        assert resume_at == 10.0

    def test_partial_window_is_dropped(self, tmp_path):
        with Checkpoint("job2", tmp_path) as ck:
            ck.write_segments([seg(0.0, 5.0, "kaydedildi")])
            ck.commit_window(0, 5.0)
            # Bu pencere yarim kaldi: isaret yazilmadan cokme oldu.
            ck.write_segments([seg(5.0, 8.0, "yarim")])

        segments, resume_at, _ = Checkpoint("job2", tmp_path).load()
        assert [s.text for s in segments] == ["kaydedildi"]
        assert resume_at == 5.0

    def test_resume_point_is_the_last_committed_window(self, tmp_path):
        with Checkpoint("job3", tmp_path) as ck:
            for index in range(3):
                ck.write_segments([seg(index * 10.0, index * 10.0 + 9.0, f"p{index}")])
                ck.commit_window(index, (index + 1) * 10.0)

        segments, resume_at, _ = Checkpoint("job3", tmp_path).load()
        assert len(segments) == 3
        assert resume_at == 30.0

    def test_metadata_survives(self, tmp_path):
        with Checkpoint("job4", tmp_path) as ck:
            ck.write_meta(model="large-v3-turbo", duration=1234.5)
            ck.commit_window(0, 10.0)

        _, _, meta = Checkpoint("job4", tmp_path).load()
        assert meta["model"] == "large-v3-turbo"
        assert meta["duration"] == 1234.5

    def test_turkish_text_survives(self, tmp_path):
        text = "Gunaydin, sicak bir cay ictik. Cocuklar okula gitti."
        with Checkpoint("job5", tmp_path) as ck:
            ck.write_segments([Segment(0.0, 3.0, text, "tr")])
            ck.commit_window(0, 3.0)

        segments, _, _ = Checkpoint("job5", tmp_path).load()
        assert segments[0].text == text
        assert segments[0].language == "tr"


class TestCorruption:
    def test_truncated_last_line_is_skipped(self, tmp_path):
        """Cokme aninda son satir yarim yazilmis olabilir."""
        checkpoint = Checkpoint("job6", tmp_path)
        with checkpoint as ck:
            ck.write_segments([seg(0.0, 5.0, "saglam")])
            ck.commit_window(0, 5.0)
        with checkpoint.path.open("a", encoding="utf-8") as handle:
            handle.write('{"t": "seg", "start": 5.0, "en')

        segments, resume_at, _ = Checkpoint("job6", tmp_path).load()
        assert [s.text for s in segments] == ["saglam"]
        assert resume_at == 5.0

    def test_missing_file_returns_empty_state(self, tmp_path):
        segments, resume_at, meta = Checkpoint("yok", tmp_path).load()
        assert segments == []
        assert resume_at == 0.0
        assert meta == {}

    def test_malformed_segment_records_are_skipped(self, tmp_path):
        checkpoint = Checkpoint("job7", tmp_path)
        checkpoint.open()
        checkpoint.close()
        checkpoint.path.write_text(
            '{"t": "seg", "start": "abc"}\n'
            '{"t": "seg", "start": 0.0, "end": 5.0, "text": "iyi"}\n'
            '{"t": "win", "index": 0, "end": 5.0}\n',
            encoding="utf-8",
        )
        segments, resume_at, _ = checkpoint.load()
        assert [s.text for s in segments] == ["iyi"]
        assert resume_at == 5.0


class TestLifecycle:
    def test_exists_reflects_content(self, tmp_path):
        checkpoint = Checkpoint("job8", tmp_path)
        assert not checkpoint.exists()
        with checkpoint as ck:
            ck.commit_window(0, 1.0)
        assert checkpoint.exists()
        assert has_checkpoint("job8", tmp_path)

    def test_clear_removes_the_file(self, tmp_path):
        checkpoint = Checkpoint("job9", tmp_path)
        with checkpoint as ck:
            ck.commit_window(0, 1.0)
        checkpoint.clear()
        assert not checkpoint.exists()

    def test_clear_is_safe_when_missing(self, tmp_path):
        Checkpoint("hic-olmadi", tmp_path).clear()

    def test_appends_across_sessions(self, tmp_path):
        """Uygulama kapanip acilinca ayni dosyaya devam edilmeli."""
        with Checkpoint("job10", tmp_path) as ck:
            ck.write_segments([seg(0.0, 5.0, "ilk oturum")])
            ck.commit_window(0, 5.0)

        with Checkpoint("job10", tmp_path) as ck:
            ck.write_segments([seg(5.0, 10.0, "ikinci oturum")])
            ck.commit_window(1, 10.0)

        segments, resume_at, _ = Checkpoint("job10", tmp_path).load()
        assert [s.text for s in segments] == ["ilk oturum", "ikinci oturum"]
        assert resume_at == 10.0
