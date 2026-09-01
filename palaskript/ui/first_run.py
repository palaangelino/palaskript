"""Ilk acilis ekrani.

Yapilandirmayi kurulum sirasinda degil BURADA yapiyoruz. Kurulum sirasinda
olcum yapmak icin modelin inmis olmasi gerekirdi (1.6 GB) ve kurulum on
dakikaya cikardi; ustelik kullanici o sirada uygulamayi hic gormemis oluyor.

Burada ise makine zaten olculmus durumda (RAM, cekirdek, disk) ve kullanici
ne secildigini gorup degistirebiliyor. Model istege bagli olarak simdi
indirilebiliyor, boylece ilk is beklemeden basliyor.

Gercek bellek olcumu ilk isten sonra kendiliginden geliyor (bkz. calibration.py).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import catalog
from ..config import Settings
from ..resources import MODEL_CATALOG, HardwareInfo, available_models, choose_profile, detect


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("muted", True)
    return label


def _tier_note(hw: HardwareInfo) -> str:
    if hw.total_ram_gb < 6.5:
        return (
            "Belleğiniz sınırlı olduğu için küçük model seçildi. Türkçede kalitesi "
            "belirgin şekilde düşük olacak."
        )
    if hw.total_ram_gb < 11.5:
        return (
            "8 GB sınıfı bir makine tespit edildi. Large v3 Turbo sığıyor; yığın "
            "boyutu ve pencere buna göre küçültüldü."
        )
    return "Belleğiniz rahat. En yüksek kaliteli ayarlar seçildi."


class FirstRunDialog(QDialog):
    """Ilk acilista bir kez gosterilir."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Palaskript kurulumu")
        self.setMinimumWidth(600)
        self._settings = settings
        self._hw = detect()

        layout = QVBoxLayout(self)

        intro = QLabel("<b>Bilgisayarınız incelendi</b>")
        layout.addWidget(intro)
        layout.addWidget(QLabel(self._hw.describe()))
        layout.addWidget(_muted(f"Boş disk: {self._hw.free_disk_gb:.0f} GB"))
        layout.addSpacing(6)
        layout.addWidget(_muted(_tier_note(self._hw)))

        box = QGroupBox("Kullanılacak model")
        box_layout = QVBoxLayout(box)

        self.model_combo = QComboBox()
        gates = available_models(self._hw)
        profile = choose_profile(self._hw)
        for name, spec in MODEL_CATALOG.items():
            suffix = " (önerilen)" if name == profile.model else ""
            self.model_combo.addItem(
                f"{spec.label}{suffix}  -  {spec.download_gb:.1f} GB indirilecek", name
            )
            if gates.get(name):
                index = self.model_combo.count() - 1
                item = self.model_combo.model().item(index)
                if item is not None:
                    item.setEnabled(False)
                    item.setToolTip(gates[name])
        chosen = self.model_combo.findData(profile.model)
        self.model_combo.setCurrentIndex(max(0, chosen))
        box_layout.addWidget(self.model_combo)

        self.profile_label = _muted("")
        box_layout.addWidget(self.profile_label)

        self.low_memory = QCheckBox("Düşük bellek modu (aynı anda başka ağır işler yapacaksanız)")
        self.low_memory.setChecked(self._settings.low_memory_mode)
        self.low_memory.stateChanged.connect(self._refresh_profile)
        box_layout.addWidget(self.low_memory)

        layout.addWidget(box)

        self.download_now = QCheckBox("Modeli şimdi indir (ilk iş beklemeden başlasın)")
        self.download_now.setChecked(True)
        layout.addWidget(self.download_now)
        layout.addWidget(
            _muted(
                "İndirmezseniz ilk işi başlattığınızda otomatik olarak inecek. "
                "Model bir kez iniyor ve bilgisayarınızda kalıyor."
            )
        )

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.progress_label = _muted("")
        self.progress_label.hide()
        layout.addWidget(self.progress_label)

        layout.addSpacing(8)
        layout.addWidget(
            _muted(
                "Not: bu ayarlar tahmine dayanıyor. İlk işiniz bittiğinde uygulama bu "
                "makinedeki gerçek bellek kullanımını ölçüp ayarları kendisi düzeltir."
            )
        )

        layout.addSpacing(4)
        credit = _muted("2026 © Selçuk Ağabey'in fikridir, kopyalanamaz.")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credit)

        row = QHBoxLayout()
        row.addStretch(1)
        self.start_button = QPushButton("Başla")
        self.start_button.setDefault(True)
        self.start_button.setProperty("primary", True)
        self.start_button.clicked.connect(self._accept)
        row.addWidget(self.start_button)
        skip = QPushButton("Şimdilik atla")
        skip.clicked.connect(self.reject)
        row.addWidget(skip)
        layout.addLayout(row)

        self.model_combo.currentIndexChanged.connect(self._refresh_profile)
        self._refresh_profile()

    # ------------------------------------------------------------- yardimci

    def _refresh_profile(self) -> None:
        model = self.model_combo.currentData()
        profile = choose_profile(
            self._hw,
            model_override=model,
            low_memory_mode=self.low_memory.isChecked(),
        )
        self.profile_label.setText(f"Ayarlar: {profile.describe()}")

    def _accept(self) -> None:
        self._settings.model = self.model_combo.currentData() or "auto"
        self._settings.low_memory_mode = self.low_memory.isChecked()

        if not self.download_now.isChecked():
            self.accept()
            return

        model = self._settings.model
        if model == "auto":
            model = choose_profile(self._hw, low_memory_mode=self._settings.low_memory_mode).model
        if catalog.is_downloaded(model):
            self.accept()
            return

        self.start_button.setEnabled(False)
        self.model_combo.setEnabled(False)
        self.download_now.setEnabled(False)
        self.progress.show()
        self.progress_label.show()

        def report(fraction: float, message: str) -> None:
            self.progress.setValue(int(fraction * 100))
            self.progress_label.setText(message)
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()

        try:
            catalog.ensure_model(model, progress=report)
        except catalog.ModelDownloadError as exc:
            # Indirme basarisiz olsa da uygulamayi acmali: ilk iste tekrar denenecek.
            self.progress_label.setText(f"{exc}  (ilk işte tekrar denenecek)")
            self.start_button.setEnabled(True)
            self.start_button.setText("Yine de devam et")
            self.start_button.clicked.disconnect()
            self.start_button.clicked.connect(self.accept)
            return

        self.accept()

    def result_settings(self) -> Settings:
        return self._settings


def should_show(settings_path) -> bool:  # noqa: ANN001 - Path
    """Ayar dosyasi yoksa ilk acilis demektir."""
    return not settings_path.exists()


def maybe_run(parent: QWidget | None = None) -> Settings | None:
    """Ilk acilissa diyalogu goster ve ayarlari kaydet."""
    from .. import config, paths

    if not should_show(paths.settings_file()):
        return None

    settings = config.load()
    dialog = FirstRunDialog(settings, parent)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.exec()
    # Atlansa da ayarlari yaziyoruz: diyalog bir daha acilmasin.
    result = dialog.result_settings()
    config.save(result)
    return result
