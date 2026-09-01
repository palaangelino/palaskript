"""Ayarlar diyalogu.

Donanim profili paneli burada onemli: kullanicinin RAM tablosunu ezberlemesi
beklenmiyor, uygulama neyi neden sectigini gosteriyor ve bellege sigmayan
modeller sebebiyle birlikte pasif geliyor.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import catalog, ytdlp_update
from ..config import Settings
from ..resources import MODEL_CATALOG, available_models, choose_profile, detect

_LANGUAGES = [
    ("auto", "Otomatik (TR + EN karışık içerik için)"),
    ("tr", "Türkçe (zorla)"),
    ("en", "İngilizce (zorla)"),
]

_TIMESTAMP_MODES = [
    ("interval", "Belirli aralıklarla"),
    ("paragraph", "Her paragrafta"),
    ("none", "Hiç"),
]

_COOKIE_BROWSERS = [
    ("none", "Kullanma"),
    ("chrome", "Chrome"),
    ("edge", "Edge"),
    ("firefox", "Firefox"),
    ("brave", "Brave"),
]

_SUB_POLICIES = [
    ("ask", "Sor (önerilen)"),
    ("always", "Her zaman hazır altyazıyı kullan"),
    ("never", "Her zaman Whisper ile yaz"),
]


def _combo(pairs: list[tuple[str, str]], current: str) -> QComboBox:
    box = QComboBox()
    for value, label in pairs:
        box.addItem(label, value)
    index = box.findData(current)
    if index >= 0:
        box.setCurrentIndex(index)
    return box


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(620)
        self._settings = settings
        self._hw = detect()

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._transcription_tab(), "Transkripsiyon")
        tabs.addTab(self._document_tab(), "Belge")
        tabs.addTab(self._system_tab(), "YouTube ve sistem")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_model_warning()

    # -------------------------------------------------------------- sekmeler

    def _transcription_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        profile = choose_profile(self._hw)
        info = QGroupBox("Donanım profili")
        info_layout = QVBoxLayout(info)
        detected = QLabel(f"Tespit edilen: {self._hw.describe()}")
        detected.setWordWrap(True)
        info_layout.addWidget(detected)
        chosen = QLabel(f"Otomatik seçim: {profile.describe()}")
        chosen.setWordWrap(True)
        info_layout.addWidget(chosen)
        outer.addWidget(info)

        form_box = QGroupBox("Model ve dil")
        form = QFormLayout(form_box)

        self.model_combo = QComboBox()
        self.model_combo.addItem("Otomatik (donanıma göre seç)", "auto")
        gates = available_models(self._hw)
        for name, spec in MODEL_CATALOG.items():
            ram = spec.ram_estimate_gb(profile.batch_size)
            self.model_combo.addItem(f"{spec.label}  -  ~{ram:.1f} GB RAM", name)
            reason = gates.get(name)
            if reason:
                index = self.model_combo.count() - 1
                model = self.model_combo.model()
                if isinstance(model, QStandardItemModel):
                    item = model.item(index)
                    if item is not None:
                        item.setEnabled(False)
                        item.setToolTip(reason)
                self.model_combo.setItemData(
                    index, f"{spec.label} (kullanılamıyor: {reason})", Qt.ItemDataRole.ToolTipRole
                )
        index = self.model_combo.findData(self._settings.model)
        self.model_combo.setCurrentIndex(index if index >= 0 else 0)
        self.model_combo.currentIndexChanged.connect(self._refresh_model_warning)
        form.addRow("Model", self.model_combo)

        self.model_warning = QLabel()
        self.model_warning.setWordWrap(True)
        self.model_warning.setStyleSheet("color: #b00020;")
        form.addRow("", self.model_warning)

        self.language_combo = _combo(_LANGUAGES, self._settings.language)
        form.addRow("Dil", self.language_combo)

        hint = QLabel(
            "Video tek dilliyse dili elle zorlamak hem daha hızlı hem daha doğru sonuç verir."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        form.addRow("", hint)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, max(1, self._hw.logical_cores))
        self.threads_spin.setSpecialValueText(f"Otomatik ({self._hw.physical_cores})")
        self.threads_spin.setValue(self._settings.cpu_threads or 0)
        form.addRow("İş parçacığı", self.threads_spin)

        self.low_memory_check = QCheckBox(
            "Düşük bellek modu (yığın 1, küçük pencere, küçük model)"
        )
        self.low_memory_check.setChecked(self._settings.low_memory_mode)
        self.low_memory_check.setToolTip(
            "Aynı anda başka ağır işler çalıştıracaksanız veya bellek yetersizliği "
            "yaşadıysanız açın. İşlem yavaşlar ama güvenli tarafta kalır."
        )
        form.addRow("", self.low_memory_check)

        outer.addWidget(form_box)
        outer.addWidget(self._models_box())
        outer.addStretch(1)
        return page

    def _models_box(self) -> QWidget:
        box = QGroupBox("İndirilmiş modeller")
        layout = QVBoxLayout(box)
        self.models_label = QLabel()
        self.models_label.setWordWrap(True)
        layout.addWidget(self.models_label)

        row = QHBoxLayout()
        refresh = QPushButton("Yenile")
        refresh.clicked.connect(self._refresh_models_label)
        row.addWidget(refresh)

        delete = QPushButton("Seçili modeli sil")
        delete.clicked.connect(self._delete_model)
        delete.setToolTip("Yer açmak için. Tekrar gerektiğinde otomatik iner.")
        row.addWidget(delete)
        row.addStretch(1)
        layout.addLayout(row)

        self._refresh_models_label()
        return box

    def _document_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        stamp_box = QGroupBox("Zaman damgaları")
        form = QFormLayout(stamp_box)
        self.timestamp_combo = _combo(_TIMESTAMP_MODES, self._settings.timestamp_mode)
        form.addRow("Gösterim", self.timestamp_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setSuffix(" dakika")
        self.interval_spin.setValue(self._settings.timestamp_interval_minutes)
        form.addRow("Aralık", self.interval_spin)
        outer.addWidget(stamp_box)

        chapter_box = QGroupBox("Bölümler")
        chapter_form = QFormLayout(chapter_box)
        self.chapters_check = QCheckBox("Bölüm başlıkları, içindekiler ve PDF yer imleri üret")
        self.chapters_check.setChecked(self._settings.use_chapters)
        self.chapters_check.setToolTip(
            "Video kendi bölüm işaretlerini taşıyorsa onlar kullanılır. Taşımıyorsa "
            "belirli aralıklarla zaman başlığı konur."
        )
        chapter_form.addRow("", self.chapters_check)

        self.auto_chapter_spin = QSpinBox()
        self.auto_chapter_spin.setRange(5, 60)
        self.auto_chapter_spin.setSuffix(" dakika")
        self.auto_chapter_spin.setValue(self._settings.auto_chapter_minutes)
        chapter_form.addRow("Video bölüm taşımıyorsa", self.auto_chapter_spin)
        outer.addWidget(chapter_box)

        out_box = QGroupBox("Çıktı")
        out_form = QFormLayout(out_box)
        row = QHBoxLayout()
        self.output_edit = QLineEdit(self._settings.output_dir)
        row.addWidget(self.output_edit, 1)
        browse = QPushButton("Seç...")
        browse.clicked.connect(self._pick_output_dir)
        row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        out_form.addRow("Klasör", container)

        self.pdf_check = QCheckBox("PDF üret")
        self.pdf_check.setChecked(self._settings.export_pdf)
        out_form.addRow("", self.pdf_check)

        self.txt_check = QCheckBox("TXT üret")
        self.txt_check.setChecked(self._settings.export_txt)
        out_form.addRow("", self.txt_check)

        self.keep_audio_check = QCheckBox("İndirilen sesi sakla (Opus, video başına ~40 MB)")
        self.keep_audio_check.setChecked(self._settings.keep_audio)
        out_form.addRow("", self.keep_audio_check)
        outer.addWidget(out_box)

        outer.addStretch(1)
        return page

    def _system_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        yt_box = QGroupBox("YouTube")
        form = QFormLayout(yt_box)

        self.subtitle_combo = _combo(_SUB_POLICIES, self._settings.manual_subtitle_policy)
        form.addRow("Hazır altyazı varsa", self.subtitle_combo)
        note = QLabel(
            "İnsan eliyle yazılmış altyazı 3 saatlik işlemi 2 saniyeye indirir. "
            "Otomatik üretilmiş altyazılar Türkçede noktalama taşımadığı için kullanılmaz."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        form.addRow("", note)

        self.cookie_combo = _combo(_COOKIE_BROWSERS, self._settings.cookie_browser)
        form.addRow("Tarayıcı çerezi", self.cookie_combo)
        cookie_note = QLabel(
            "Yaş kısıtlı veya özel videolar için gerekir. Tarayıcının kapalı olması gerekebilir."
        )
        cookie_note.setWordWrap(True)
        cookie_note.setStyleSheet("color: #666;")
        form.addRow("", cookie_note)
        outer.addWidget(yt_box)

        update_box = QGroupBox("yt-dlp")
        update_layout = QVBoxLayout(update_box)
        self.ytdlp_label = QLabel()
        self.ytdlp_label.setWordWrap(True)
        update_layout.addWidget(self.ytdlp_label)
        warning = QLabel(
            "YouTube sık değiştiği için yt-dlp zamanla bozulur. Link indirmede hata "
            "alıyorsanız önce burayı güncelleyin."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #666;")
        update_layout.addWidget(warning)

        button_row = QHBoxLayout()
        update_button = QPushButton("yt-dlp'yi guncelle")
        update_button.clicked.connect(self._update_ytdlp)
        button_row.addWidget(update_button)
        button_row.addStretch(1)
        update_layout.addLayout(button_row)
        outer.addWidget(update_box)

        self._refresh_ytdlp_label()
        outer.addStretch(1)
        return page

    # ------------------------------------------------------------ yardimci

    def _refresh_models_label(self) -> None:
        downloaded = catalog.downloaded_models()
        if not downloaded:
            self.models_label.setText(
                "Henüz model inmedi. İlk iş başlatıldığında otomatik olarak inecek."
            )
            return
        parts = []
        for name in downloaded:
            size = catalog.dir_size_bytes(catalog.model_dir(name)) / 1024**3
            parts.append(f"{name} ({size:.1f} GB)")
        self.models_label.setText("Diskte: " + ", ".join(parts))

    def _delete_model(self) -> None:
        downloaded = catalog.downloaded_models()
        if not downloaded:
            QMessageBox.information(self, "Model yok", "Silinecek indirilmiş model yok.")
            return
        current = self.model_combo.currentData()
        target = current if current in downloaded else downloaded[0]
        answer = QMessageBox.question(
            self,
            "Modeli sil",
            f"{target} modeli diskten silinsin mi? Tekrar gerektiğinde yeniden iner.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            catalog.delete_model(target)
            self._refresh_models_label()

    def _refresh_model_warning(self) -> None:
        selected = self.model_combo.currentData()
        if selected in (None, "auto"):
            self.model_warning.setText("")
            return
        reason = available_models(self._hw).get(selected)
        self.model_warning.setText(reason or "")

    def _refresh_ytdlp_label(self) -> None:
        version = ytdlp_update.installed_version() or "bilinmiyor"
        source = "kullanıcı dizini" if ytdlp_update.is_user_managed() else "uygulamayla geldi"
        self.ytdlp_label.setText(f"Kurulu surum: {version} ({source})")

    def _update_ytdlp(self) -> None:
        dialog = QProgressDialog("yt-dlp güncelleniyor...", "Vazgeç", 0, 100, self)
        dialog.setWindowTitle("Güncelleme")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)

        def report(fraction: float, message: str) -> None:
            dialog.setLabelText(message)
            dialog.setValue(int(fraction * 100))

        try:
            version = ytdlp_update.update(report)
        except ytdlp_update.UpdateError as exc:
            dialog.close()
            QMessageBox.warning(self, "Güncellenemedi", str(exc))
            return
        dialog.close()
        QMessageBox.information(
            self,
            "Güncellendi",
            f"yt-dlp {version} kuruldu. Değişiklik uygulama yeniden başlatıldığında etkinleşir.",
        )
        self._refresh_ytdlp_label()

    def _pick_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Çıktı klasörü", self.output_edit.text()
        )
        if directory:
            self.output_edit.setText(directory)

    # ------------------------------------------------------------- sonuc

    def result_settings(self) -> Settings:
        s = self._settings
        s.model = self.model_combo.currentData() or "auto"
        s.language = self.language_combo.currentData()
        s.cpu_threads = self.threads_spin.value() or None
        s.low_memory_mode = self.low_memory_check.isChecked()
        s.timestamp_mode = self.timestamp_combo.currentData()
        s.timestamp_interval_minutes = self.interval_spin.value()
        s.use_chapters = self.chapters_check.isChecked()
        s.auto_chapter_minutes = self.auto_chapter_spin.value()
        s.output_dir = str(Path(self.output_edit.text()).expanduser())
        s.export_pdf = self.pdf_check.isChecked()
        s.export_txt = self.txt_check.isChecked()
        s.keep_audio = self.keep_audio_check.isChecked()
        s.manual_subtitle_policy = self.subtitle_combo.currentData()
        s.cookie_browser = self.cookie_combo.currentData()
        return s
