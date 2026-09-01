"""Kalici is kuyrugu.

En onemli davranis: uygulama duzgun kapanmadiginda 'running' durumunda kalan
isler acilista tekrar siraya alinmali. Ara kayit durdugu icin is kaldigi yerden
devam ediyor, bastan baslamiyor.
"""

from __future__ import annotations

import pytest

from palaskript.datatypes import SourceInfo
from palaskript.jobqueue.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "queue.db")
    yield database
    database.close()


def yt(video_id: str, title: str = "Video", duration: float = 3600.0) -> SourceInfo:
    return SourceInfo(
        kind="youtube",
        source_id=f"youtube:{video_id}",
        title=title,
        duration=duration,
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel="Kanal",
    )


class TestAdding:
    def test_add_and_list(self, db):
        job = db.add(yt("abc"), "https://www.youtube.com/watch?v=abc")
        jobs = db.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == job.id
        assert jobs[0].status == "pending"

    def test_add_many_skips_duplicates_already_queued(self, db):
        added, skipped = db.add_many([yt("abc"), yt("abc"), yt("def")])
        assert len(added) == 2
        assert len(skipped) == 1

    def test_finished_video_can_be_added_again(self, db):
        """Ayni videoyu daha iyi bir modelle tekrar yazmak istenebilir."""
        job = db.add(yt("abc"), "raw")
        db.mark_done(job.id, pdf_path="a.pdf", txt_path=None, audio_path=None)
        added, skipped = db.add_many([yt("abc")])
        assert len(added) == 1
        assert not skipped

    def test_positions_increment(self, db):
        first = db.add(yt("a"), "a")
        second = db.add(yt("b"), "b")
        assert second.position > first.position


class TestStatusTransitions:
    def test_running_then_done(self, db):
        job = db.add(yt("abc"), "raw")
        db.mark_running(job.id)
        assert db.get(job.id).status == "running"
        db.mark_done(job.id, pdf_path="x.pdf", txt_path="x.txt", audio_path=None)
        stored = db.get(job.id)
        assert stored.status == "done"
        assert stored.progress == 1.0
        assert stored.pdf_path == "x.pdf"
        assert stored.finished_at

    def test_failed_records_the_error(self, db):
        job = db.add(yt("abc"), "raw")
        db.mark_failed(job.id, "yt-dlp patladi")
        assert db.get(job.id).error == "yt-dlp patladi"

    def test_retry_clears_error_and_requeues(self, db):
        job = db.add(yt("abc"), "raw")
        db.mark_failed(job.id, "hata")
        db.retry(job.id)
        stored = db.get(job.id)
        assert stored.status == "pending"
        assert stored.error is None
        assert stored.progress == 0.0

    def test_cancel(self, db):
        job = db.add(yt("abc"), "raw")
        db.mark_cancelled(job.id)
        assert db.get(job.id).status == "cancelled"

    def test_very_long_error_is_truncated(self, db):
        job = db.add(yt("abc"), "raw")
        db.mark_failed(job.id, "x" * 5000)
        assert len(db.get(job.id).error) <= 2000


class TestCrashRecovery:
    def test_reset_stale_requeues_running_jobs(self, db):
        """Uygulama cokerse 'running' kalan is acilista tekrar siraya girmeli."""
        job = db.add(yt("abc"), "raw")
        db.mark_running(job.id)
        db.update_progress(job.id, stage="transcribe", progress=0.4)

        assert db.reset_stale() == 1
        stored = db.get(job.id)
        assert stored.status == "pending"
        assert stored.stage is None
        # Ilerleme korunuyor: kullanici ne kadar ilerlendigini gorsun.
        assert stored.progress == pytest.approx(0.4)

    def test_reset_stale_leaves_other_statuses_alone(self, db):
        done = db.add(yt("a"), "a")
        db.mark_done(done.id, pdf_path=None, txt_path=None, audio_path=None)
        failed = db.add(yt("b"), "b")
        db.mark_failed(failed.id, "hata")

        assert db.reset_stale() == 0
        assert db.get(done.id).status == "done"
        assert db.get(failed.id).status == "failed"


class TestSubtitleDecision:
    def test_awaiting_decision_then_resolve(self, db):
        job = db.add(yt("abc"), "raw")
        db.mark_awaiting_decision(job.id, ["tr", "en"])
        stored = db.get(job.id)
        assert stored.status == "awaiting_decision"
        assert stored.manual_sub_langs == "tr,en"

        db.decide_subtitles(job.id, True)
        stored = db.get(job.id)
        assert stored.status == "pending"
        assert stored.use_subtitles is True

    def test_undecided_is_none_not_false(self, db):
        """None (karar verilmedi) ile False (Whisper secildi) ayri anlamlar."""
        job = db.add(yt("abc"), "raw")
        assert db.get(job.id).use_subtitles is None
        db.decide_subtitles(job.id, False)
        assert db.get(job.id).use_subtitles is False


class TestOrdering:
    def test_next_pending_follows_position(self, db):
        first = db.add(yt("a"), "a")
        db.add(yt("b"), "b")
        assert db.next_pending().id == first.id

    def test_move_up_changes_order(self, db):
        first = db.add(yt("a"), "a")
        second = db.add(yt("b"), "b")
        db.move(second.id, -1)
        assert [j.id for j in db.list_jobs()] == [second.id, first.id]

    def test_move_beyond_edges_is_ignored(self, db):
        job = db.add(yt("a"), "a")
        db.move(job.id, -1)
        db.move(job.id, 1)
        assert db.list_jobs()[0].id == job.id

    def test_pending_after_finds_the_next_one(self, db):
        """On indirme bunu kullaniyor: siradaki isin sesini simdiden indirmek icin."""
        first = db.add(yt("a"), "a")
        second = db.add(yt("b"), "b")
        assert db.pending_after(first.id).id == second.id

    def test_pending_after_returns_none_at_the_end(self, db):
        job = db.add(yt("a"), "a")
        assert db.pending_after(job.id) is None

    def test_pending_after_skips_non_pending(self, db):
        first = db.add(yt("a"), "a")
        second = db.add(yt("b"), "b")
        third = db.add(yt("c"), "c")
        db.mark_done(second.id, pdf_path=None, txt_path=None, audio_path=None)
        assert db.pending_after(first.id).id == third.id


class TestMaintenance:
    def test_delete(self, db):
        job = db.add(yt("a"), "a")
        db.delete(job.id)
        assert db.get(job.id) is None

    def test_clear_finished_removes_done_and_cancelled_only(self, db):
        done = db.add(yt("a"), "a")
        db.mark_done(done.id, pdf_path=None, txt_path=None, audio_path=None)
        cancelled = db.add(yt("b"), "b")
        db.mark_cancelled(cancelled.id)
        failed = db.add(yt("c"), "c")
        db.mark_failed(failed.id, "hata")
        pending = db.add(yt("d"), "d")

        assert db.clear_finished() == 2
        remaining = {j.id for j in db.list_jobs()}
        assert remaining == {failed.id, pending.id}

    def test_counts(self, db):
        db.add(yt("a"), "a")
        done = db.add(yt("b"), "b")
        db.mark_done(done.id, pdf_path=None, txt_path=None, audio_path=None)
        counts = db.counts()
        assert counts["pending"] == 1
        assert counts["done"] == 1

    def test_survives_reopen(self, db, tmp_path):
        """Kuyruk uygulama kapansa da durmali."""
        job = db.add(yt("a", title="Kalici is"), "raw")
        db.close()

        reopened = Database(tmp_path / "queue.db")
        try:
            assert reopened.get(job.id).title == "Kalici is"
        finally:
            reopened.close()


class TestJobHelpers:
    def test_status_label_shows_stage_while_running(self, db):
        job = db.add(yt("a"), "a")
        db.mark_running(job.id)
        db.update_progress(job.id, stage="transcribe")
        assert db.get(job.id).status_label == "Yazılıyor"

    def test_status_label_falls_back_to_status(self, db):
        job = db.add(yt("a"), "a")
        assert db.get(job.id).status_label == "Bekliyor"

    def test_to_source_info_round_trips_youtube(self, db):
        job = db.add(yt("abc", title="Konusma"), "raw")
        info = db.get(job.id).to_source_info()
        assert info.kind == "youtube"
        assert info.title == "Konusma"
        assert info.url.endswith("abc")

    def test_is_active_flags(self, db):
        job = db.add(yt("a"), "a")
        assert db.get(job.id).is_active
        db.mark_done(job.id, pdf_path=None, txt_path=None, audio_path=None)
        assert not db.get(job.id).is_active
