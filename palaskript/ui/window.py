"""Ana pencere: kuyruk tablosu, ekleme akisi, durum cubugu.

Arayuz veritabanini duzenli araliklarla okuyor, isci surecten dogrudan sinyal
almiyor. Bu bilerek boyle: is ayri bir surecte calisiyor ve tek gercek kaynak
SQLite. Boylece uygulama kapanip acilsa da tablo ayni bilgiyi gosteriyor.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, config, paths, updates
from ..chapters import format_timestamp
from ..config import Settings
from ..datatypes import SourceInfo
from ..jobqueue.db import Database, Job
from ..jobqueue.orchestrator import Orchestrator, cleanup_orphan_cache
from ..power import keep_awake
from ..resources import choose_profile, detect
from ..source import resolver
from . import theme
from .add_dialog import AddDialog
from .progress import ProgressCell
from .settings_dialog import SettingsDialog

_REFRESH_MS = 500

_COLUMNS = ["Başlık", "Süre", "Durum", "İlerleme", "Kalan"]
_COL_TITLE, _COL_DURATION, _COL_STATUS, _COL_PROGRESS, _COL_ETA = range(5)


class UpdateChecker(QObject):
    """GitHub'da yeni surum var mi diye arka planda bakar.

    Ag cagrisi acilisi geciktirmemeli; bu yuzden ayri bir is parcaciginda
    calisiyor ve sonuc gelene kadar arayuz normal sekilde kullanilabiliyor.
    Hata durumunda sessiz kaliyor: guncelleme denetimi kullanicinin isini
    engellememeli.
    """

    found = Signal(object)

    def __init__(self, repo: str) -> None:
        super().__init__()
        self._repo = repo

    def run(self) -> None:
        try:
            release = updates.check(self._repo)
        except updates.UpdateError:
            release = None
        except Exception:  # noqa: BLE001 - denetim hicbir sekilde uygulamayi dusurmemeli
            release = None
        self.found.emit(release)


class ResolveWorker(QObject):
    """Girdileri arka planda cozer. Ag cagrilari arayuzu dondurmasin diye."""

    finished = Signal(list, list)

    def __init__(self, raw_lines: list[str], settings: Settings, known: set[str]) -> None:
        super().__init__()
        self._lines = raw_lines
        self._settings = settings
        self._known = known

    def run(self) -> None:
        sources, errors = resolver.resolve_many(
            self._lines,
            cookie_browser=self._settings.cookie_browser,
            known_ids=self._known,
        )
        self.finished.emit(sources, [f"{e.raw}: {e.message}" for e in errors])


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        paths.ensure_dirs()

        self.settings = config.load()
        self.db = Database()
        resumed = self.db.reset_stale()
        cleanup_orphan_cache(self.db)

        self.orchestrator = Orchestrator(
            self.db,
            self.settings,
            on_notify=self._notify,
        )

        self._rows: list[str] = []
        self._resolve_thread: QThread | None = None
        self._resolve_worker: ResolveWorker | None = None
        self._last_clipboard = ""
        self._update_thread: QThread | None = None
        self._update_worker: UpdateChecker | None = None
        self._pending_release = None
        # Is basina son GERCEK kalan sure ve alindigi an. Bildirimler
        # dakikalar arayla geldigi icin arasi burada sayiliyor.
        self._eta_anchors: dict[str, tuple[float, float]] = {}

        self.setWindowTitle(f"Palaskript {__version__}")
        self.resize(1000, 620)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_toolbar()
        self._build_tray()

        self.orchestrator.start()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_REFRESH_MS)
        self.refresh()

        if resumed:
            self.statusBar().showMessage(
                f"{resumed} yarım kalmış iş kaldığı yerden devam edecek.", 8000
            )

        self.start_update_check()

    # ------------------------------------------------------------- kurulum

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.clipboard_bar = self._banner("neutral")
        self.clipboard_label = QLabel()
        self.clipboard_add = QPushButton("Kuyruğa ekle")
        self.clipboard_dismiss = QPushButton("Yoksay")
        self.clipboard_add.clicked.connect(self._add_from_clipboard)
        self.clipboard_dismiss.clicked.connect(self._dismiss_clipboard)
        self._fill_banner(
            self.clipboard_bar,
            self.clipboard_label,
            [self.clipboard_add, self.clipboard_dismiss],
        )
        self.clipboard_bar.hide()
        layout.addWidget(self.clipboard_bar)

        self.update_bar = self._banner("neutral")
        self.update_label = QLabel()
        self.update_install = QPushButton("Güncelle")
        self.update_install.setProperty("primary", True)
        self.update_later = QPushButton("Sonra")
        self.update_install.clicked.connect(self._install_update)
        self.update_later.clicked.connect(self.update_bar.hide)
        self._fill_banner(
            self.update_bar, self.update_label, [self.update_install, self.update_later]
        )
        self.update_bar.hide()
        layout.addWidget(self.update_bar)

        self.decision_bar = self._banner("accent")
        self.decision_label = QLabel()
        self.decision_subs = QPushButton("Hazır altyazıyı kullan")
        self.decision_subs.setProperty("primary", True)
        self.decision_whisper = QPushButton("Palaskript ile yaz")
        self.decision_subs.clicked.connect(lambda: self._decide_all(True))
        self.decision_whisper.clicked.connect(lambda: self._decide_all(False))
        self._fill_banner(
            self.decision_bar,
            self.decision_label,
            [self.decision_subs, self.decision_whisper],
        )
        self.decision_bar.hide()
        layout.addWidget(self.decision_bar)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda: self._open_output("pdf"))

        header = self.table.horizontalHeader()
        # Basliklarin hizasi stil sayfasindan gelmiyor, kodla veriliyor.
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(_COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col in (_COL_DURATION, _COL_STATUS, _COL_PROGRESS, _COL_ETA):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(_COL_PROGRESS, 160)
        layout.addWidget(self.table, 1)

        self.setCentralWidget(central)

        self.profile_label = QLabel()
        self.statusBar().addPermanentWidget(self.profile_label)

        separator = QLabel("|")
        separator.setProperty("muted", True)
        self.statusBar().addPermanentWidget(separator)
        self.statusBar().addPermanentWidget(theme.credit_widget())

        self._update_profile_label()

    def _banner(self, tone: str) -> QWidget:
        """Bilgilendirme cubugu. Renkler paletten geliyor (bkz. theme.py)."""
        bar = QWidget()
        bar.setStyleSheet(theme.banner_style(tone=tone))
        return bar

    def _fill_banner(self, bar: QWidget, label: QLabel, buttons: list[QPushButton]) -> None:
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        for button in buttons:
            row.addWidget(button)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Ana")
        bar.setMovable(False)
        self.addToolBar(bar)

        add = QAction("Ekle", self)
        add.setShortcut("Ctrl+N")
        # QAction.triggered 'checked' degerini (bool) yolluyor ve
        # open_add_dialog opsiyonel bir parametre aldigi icin Qt onu
        # metin sanip veriyordu. Lambda ile sinyalin argumanini yutuyoruz.
        add.triggered.connect(lambda: self.open_add_dialog())
        bar.addAction(add)

        bar.addSeparator()
        self.pause_action = QAction("Duraklat", self)
        self.pause_action.triggered.connect(self._toggle_pause)
        bar.addAction(self.pause_action)

        clear = QAction("Bitmişleri temizle", self)
        clear.triggered.connect(self._clear_finished)
        bar.addAction(clear)

        bar.addSeparator()
        open_out = QAction("Çıktı klasörü", self)
        open_out.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.output_dir))
        )
        bar.addAction(open_out)

        update_action = QAction("Güncelleme denetle", self)
        update_action.triggered.connect(lambda: self.start_update_check(manual=True))
        bar.addAction(update_action)

        settings_action = QAction("Ayarlar", self)
        settings_action.triggered.connect(self.open_settings)
        bar.addAction(settings_action)

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_path = paths.assets_dir() / "icon.ico"
        icon = QIcon(str(icon_path)) if icon_path.exists() else self.windowIcon()
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Palaskript")
        self.tray.show()

    # -------------------------------------------------------------- ekleme

    def open_add_dialog(self, initial: str = "") -> None:
        dialog = AddDialog(self, initial=initial)
        if dialog.exec() != AddDialog.DialogCode.Accepted:
            return
        self._resolve_and_add(resolver.parse_input_lines(dialog.raw_text()))

    def _resolve_and_add(self, lines: list[str]) -> None:
        if not lines:
            return
        if self._resolve_thread is not None:
            QMessageBox.information(
                self, "Bekleyin", "Önceki ekleme işlemi hâlâ sürüyor."
            )
            return

        self.statusBar().showMessage(f"{len(lines)} girdi çözümleniyor...")
        worker = ResolveWorker(lines, self.settings, self.db.active_source_ids())
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_resolved)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._clear_resolve_thread)
        self._resolve_thread = thread
        self._resolve_worker = worker
        thread.start()

    def _clear_resolve_thread(self) -> None:
        if self._resolve_thread is not None:
            self._resolve_thread.deleteLater()
        self._resolve_thread = None
        self._resolve_worker = None

    def _on_resolved(self, sources: list, errors: list) -> None:
        typed: list[SourceInfo] = list(sources)
        added, skipped = self.db.add_many(typed)

        parts = [f"{len(added)} iş eklendi"]
        if skipped:
            parts.append(f"{len(skipped)} tanesi zaten kuyrukta")
        if errors:
            parts.append(f"{len(errors)} girdi çözümlenemedi")
        self.statusBar().showMessage(", ".join(parts), 8000)

        if errors:
            QMessageBox.warning(
                self,
                "Bazı girdiler eklenemedi",
                "\n\n".join(str(e) for e in errors[:10]),
            )
        self.refresh()

    def _add_from_clipboard(self) -> None:
        text = QApplication.clipboard().text().strip()
        self.clipboard_bar.hide()
        self._last_clipboard = text
        if text:
            self._resolve_and_add([text])

    def _dismiss_clipboard(self) -> None:
        self._last_clipboard = QApplication.clipboard().text().strip()
        self.clipboard_bar.hide()

    def _check_clipboard(self) -> None:
        if not self.isActiveWindow() or self.clipboard_bar.isVisible():
            return
        text = QApplication.clipboard().text().strip()
        if not text or text == self._last_clipboard or "\n" in text:
            return
        if not resolver.is_url(text):
            return
        if any(job.raw_input == text for job in self.db.list_jobs()):
            self._last_clipboard = text
            return
        shown = text if len(text) <= 90 else text[:87] + "..."
        self.clipboard_label.setText(f"Panoda bir adres var: {shown}")
        self.clipboard_bar.show()

    # ---------------------------------------------------------- surukle birak

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        lines: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                lines.append(url.toLocalFile() if url.isLocalFile() else url.toString())
        elif mime.hasText():
            lines = resolver.parse_input_lines(mime.text())
        if lines:
            event.acceptProposedAction()
            self._resolve_and_add(lines)

    # -------------------------------------------------------------- tablo

    def refresh(self) -> None:
        jobs = self.db.list_jobs()
        ids = [job.id for job in jobs]

        if ids != self._rows:
            self._rebuild(jobs)
            self._rows = ids
        else:
            for row, job in enumerate(jobs):
                self._update_row(row, job)

        self._refresh_decision_bar(jobs)
        self._check_clipboard()
        self._update_status(jobs)

    def _rebuild(self, jobs: list[Job]) -> None:
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            for col in (_COL_TITLE, _COL_DURATION, _COL_STATUS, _COL_ETA):
                if self.table.item(row, col) is None:
                    self.table.setItem(row, col, QTableWidgetItem())
            self.table.setCellWidget(row, _COL_PROGRESS, ProgressCell())
            self._update_row(row, job)

    def _update_row(self, row: int, job: Job) -> None:
        title_item = self.table.item(row, _COL_TITLE)
        if title_item is None:
            return
        title_item.setText(job.title)
        title_item.setData(Qt.ItemDataRole.UserRole, job.id)
        tooltip = job.url or job.raw_input
        if job.error:
            tooltip = f"{tooltip}\n\nHata: {job.error}"
        elif job.message:
            tooltip = f"{tooltip}\n\n{job.message}"
        title_item.setToolTip(tooltip)

        self.table.item(row, _COL_DURATION).setText(
            format_timestamp(job.duration, always_hours=True) if job.duration else "-"
        )

        status_item = self.table.item(row, _COL_STATUS)
        # Calisan iste ayrintili mesaji gosteriyoruz. Sabit asama etiketi
        # ("Model hazirlaniyor") 7 dakikalik bir model indirmesi boyunca hic
        # degismiyor ve uygulama donmus gibi gorunuyor; mesaj ise kac GB
        # inildigini soyluyor.
        detail = job.message if job.status == "running" and job.message else None
        status_item.setText(detail or job.status_label)
        status_item.setToolTip(job.message or job.error or "")

        cell = self.table.cellWidget(row, _COL_PROGRESS)
        if isinstance(cell, ProgressCell):
            # Cubuk gercek bildirimler arasini kendi hesapliyor; asama ve
            # kalan sure bunun icin gerekiyor.
            cell.set_state(
                percent=job.progress * 100,
                stage=job.stage,
                eta_seconds=self._live_eta(job),
                running=job.status == "running",
                finished=job.status == "done",
            )

        self.table.item(row, _COL_ETA).setText(self._eta_text(job))

    def _live_eta(self, job: Job) -> float | None:
        """Gercek zamanli kalan sure.

        Boru hatti kalan sureyi dakikalar arayla bildiriyor; arada sabit
        durmasi "sayac donmus" izlenimi veriyor. Son bildirilen degerden
        gecen sureyi dusuyoruz. Yeni bir bildirim gelince demir yenileniyor.
        """
        if job.status != "running":
            self._eta_anchors.pop(job.id, None)
            return None
        if not job.eta_seconds or job.eta_seconds <= 0:
            return None

        now = time.monotonic()
        anchor = self._eta_anchors.get(job.id)
        if anchor is None or anchor[0] != job.eta_seconds:
            # Yeni (veya ilk) bildirim: demiri buraya at.
            self._eta_anchors[job.id] = (job.eta_seconds, now)
            return job.eta_seconds

        reported, at = anchor
        return max(0.0, reported - (now - at))

    def _eta_text(self, job: Job) -> str:
        if job.status == "done":
            return "Hazır"
        if job.status != "running":
            return "-"

        remaining = self._live_eta(job)
        if remaining is None:
            # Henuz guvenilir bir tahmin yok. Uydurmaktansa soylemiyoruz.
            return "hesaplanıyor"
        if remaining < 30:
            # Sayacin sifirda takilmasindansa durumu soyluyoruz.
            return "bitmek üzere"
        return format_timestamp(remaining, always_hours=True)

    def _selected_job(self) -> Job | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, _COL_TITLE)
        if item is None:
            return None
        job_id = item.data(Qt.ItemDataRole.UserRole)
        return self.db.get(str(job_id)) if job_id else None

    def _context_menu(self, position) -> None:  # noqa: ANN001 - Qt imzasi
        job = self._selected_job()
        if job is None:
            return

        menu = QMenu(self)
        if job.status == "awaiting_decision":
            menu.addAction(
                "Hazır altyazıyı kullan", lambda: self._decide_one(job.id, True)
            )
            menu.addAction("Palaskript ile yaz", lambda: self._decide_one(job.id, False))
            menu.addSeparator()
        if job.status == "done":
            if job.pdf_path:
                menu.addAction("PDF'i aç", lambda: self._open_path(job.pdf_path))
            if job.txt_path:
                menu.addAction("Metni aç", lambda: self._open_path(job.txt_path))
            menu.addAction("Klasörü aç", lambda: self._reveal(job.pdf_path or job.txt_path))
            menu.addSeparator()
        if job.status in ("pending", "awaiting_decision"):
            menu.addAction("Yukarı taşı", lambda: self._move(job.id, -1))
            menu.addAction("Aşağı taşı", lambda: self._move(job.id, 1))
            menu.addSeparator()
        if job.is_active:
            menu.addAction("İptal et", lambda: self._cancel(job.id))
        if job.status in ("failed", "cancelled"):
            menu.addAction("Tekrar dene", lambda: self._retry(job.id))
        if job.error:
            menu.addAction("Hatayı göster", lambda: self._show_error(job))
        menu.addSeparator()
        menu.addAction("Kuyruktan sil", lambda: self._delete(job.id))
        menu.exec(self.table.viewport().mapToGlobal(position))

    # ------------------------------------------------------------- eylemler

    def _move(self, job_id: str, delta: int) -> None:
        self.db.move(job_id, delta)
        self.refresh()

    def _cancel(self, job_id: str) -> None:
        self.orchestrator.cancel_job(job_id)
        self.refresh()

    def _retry(self, job_id: str) -> None:
        self.db.retry(job_id)
        self.refresh()

    def _delete(self, job_id: str) -> None:
        job = self.db.get(job_id)
        if job and job.is_active:
            self.orchestrator.cancel_job(job_id)
        self.db.delete(job_id)
        self.refresh()

    def _decide_one(self, job_id: str, use_subs: bool) -> None:
        self.db.decide_subtitles(job_id, use_subs)
        self.refresh()

    def _decide_all(self, use_subs: bool) -> None:
        for job in self.db.list_jobs():
            if job.status == "awaiting_decision":
                self.db.decide_subtitles(job.id, use_subs)
        self.refresh()

    def _show_error(self, job: Job) -> None:
        QMessageBox.warning(self, job.title, job.error or "Ayrıntı yok.")

    def _clear_finished(self) -> None:
        removed = self.db.clear_finished()
        cleanup_orphan_cache(self.db)
        self.statusBar().showMessage(f"{removed} kayıt temizlendi.", 5000)
        self.refresh()

    def _toggle_pause(self) -> None:
        if self.orchestrator.is_paused:
            self.orchestrator.resume()
            self.pause_action.setText("Duraklat")
        else:
            self.orchestrator.pause()
            self.pause_action.setText("Devam et")

    def _open_output(self, kind: str) -> None:
        job = self._selected_job()
        if job is None or job.status != "done":
            return
        self._open_path(job.pdf_path if kind == "pdf" else job.txt_path)

    def _open_path(self, path: str | None) -> None:
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Bulunamadı", "Dosya taşınmış veya silinmiş.")

    def _reveal(self, path: str | None) -> None:
        if not path:
            return
        target = Path(path)
        if not target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.output_dir))
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(str(target))])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    # --------------------------------------------------------------- durum

    def _refresh_decision_bar(self, jobs: list[Job]) -> None:
        waiting = [job for job in jobs if job.status == "awaiting_decision"]
        if not waiting:
            self.decision_bar.hide()
            return
        if len(waiting) == 1:
            langs = waiting[0].manual_sub_langs or "?"
            text = (
                f"\"{waiting[0].title}\" videosunda hazır altyazı var ({langs}). "
                "Altyazıyı kullanmak saniyeler sürer, yeniden yazmak saatler."
            )
        else:
            text = f"{len(waiting)} videoda hazır altyazı var. Nasıl devam edilsin?"
        self.decision_label.setText(text)
        self.decision_bar.show()

    def _update_profile_label(self) -> None:
        hw = detect()
        profile = choose_profile(
            hw,
            model_override=None if self.settings.model == "auto" else self.settings.model,
            threads_override=self.settings.cpu_threads,
            low_memory_mode=self.settings.low_memory_mode,
        )
        self.profile_label.setText(f"{hw.total_ram_gb:.0f} GB RAM  |  {profile.describe()}")
        self.profile_label.setToolTip(hw.describe())

    def _update_status(self, jobs: list[Job]) -> None:
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
        pending = counts.get("pending", 0)
        running = counts.get("running", 0)
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)

        parts = [f"{pending} bekliyor", f"{running} işleniyor", f"{done} bitti"]
        if failed:
            parts.append(f"{failed} hata")
        if keep_awake.active:
            parts.append("uyku engelleniyor")
        if self.orchestrator.is_paused:
            parts.append("DURAKLATILDI")
        self.statusBar().showMessage("  |  ".join(parts))

    def _notify(self, title: str, body: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 6000)

    # ---------------------------------------------------------- guncelleme

    def start_update_check(self, *, manual: bool = False) -> None:
        """Arka planda yeni surum var mi bak."""
        if self._update_thread is not None:
            return
        if not manual and not self.settings.check_updates:
            return
        if not manual and not updates.is_frozen():
            # Kaynaktan calisirken guncelleme onerilmiyor: gelistirici kendi
            # kopyasini git ile guncelliyor, kurulum dosyasi calistirmak
            # calisma kopyasini bozar.
            return

        repo = self.settings.update_repo or updates.DEFAULT_REPO
        if not repo:
            if manual:
                QMessageBox.information(
                    self,
                    "Güncelleme deposu yok",
                    "Ayarlardan GitHub deposunu ('kullanici/depo') girin.",
                )
            return

        worker = UpdateChecker(repo)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.found.connect(lambda release: self._on_update_found(release, manual))
        worker.found.connect(thread.quit)
        thread.finished.connect(self._clear_update_thread)
        self._update_thread = thread
        self._update_worker = worker
        thread.start()

    def _clear_update_thread(self) -> None:
        if self._update_thread is not None:
            self._update_thread.deleteLater()
        self._update_thread = None
        self._update_worker = None

    def _on_update_found(self, release, manual: bool) -> None:  # noqa: ANN001 - Release | None
        self._pending_release = release
        if release is None:
            if manual:
                QMessageBox.information(
                    self, "Güncel", f"En son sürümü kullanıyorsunuz ({__version__})."
                )
            return

        self.update_label.setText(
            f"Yeni sürüm hazır: Palaskript {release.version} "
            f"(şu an {__version__} kullanıyorsunuz)."
        )
        self.update_install.setEnabled(release.can_install)
        self.update_install.setToolTip(
            "" if release.can_install else "Bu yayında kurulum dosyası yok."
        )
        self.update_bar.show()

    def _install_update(self) -> None:
        release = self._pending_release
        if release is None:
            return

        active = [job for job in self.db.list_jobs() if job.status == "running"]
        if active:
            QMessageBox.information(
                self,
                "İşlem sürüyor",
                f"\"{active[0].title}\" işleniyor. Güncelleme için işin bitmesini "
                "bekleyin veya işi durdurun.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Güncelle",
            f"Palaskript {release.version} indirilip kurulacak.\n\n"
            "Uygulama kapanacak ve kurulum başlayacak. Kuyruğunuz, ayarlarınız ve "
            "indirilmiş modeller korunur.\n\nDevam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        dialog = QProgressDialog("Güncelleme indiriliyor...", "Vazgeç", 0, 100, self)
        dialog.setWindowTitle("Güncelleme")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)

        def report(fraction: float, message: str) -> None:
            dialog.setValue(int(fraction * 100))
            dialog.setLabelText(message)
            QApplication.processEvents()

        try:
            installer = updates.download_installer(release, progress=report)
        except updates.UpdateError as exc:
            dialog.close()
            QMessageBox.warning(self, "Güncellenemedi", str(exc))
            return
        dialog.close()

        try:
            updates.launch_installer(installer)
        except updates.UpdateError as exc:
            QMessageBox.warning(self, "Güncellenemedi", str(exc))
            return

        # Kurulum calisan dosyalarin uzerine yazamiyor; hemen kapaniyoruz.
        self._timer.stop()
        self.orchestrator.stop(wait=True, timeout=10.0)
        keep_awake.reset()
        self.db.close()
        QApplication.quit()

    # -------------------------------------------------------------- ayarlar

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        self.settings = dialog.result_settings()
        config.save(self.settings)
        self.orchestrator.update_settings(self.settings)
        self._update_profile_label()
        self.statusBar().showMessage("Ayarlar kaydedildi.", 4000)

    # -------------------------------------------------------------- kapanis

    def closeEvent(self, event: QCloseEvent) -> None:
        active = [job for job in self.db.list_jobs() if job.status == "running"]
        if active:
            answer = QMessageBox.question(
                self,
                "İşlem sürüyor",
                f"\"{active[0].title}\" hâlâ işleniyor.\n\n"
                "Şimdi kapatırsanız iş kaldığı yerden devam etmek üzere kaydedilir. "
                "Kapatılsın mı?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        self._timer.stop()
        self.orchestrator.stop(wait=True, timeout=15.0)
        keep_awake.reset()
        self.db.close()
        event.accept()
