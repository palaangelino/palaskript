"""Kuyruga ekleme diyalogu.

Tek kutu: linkler satir satir yapistiriliyor, ayni yerden dosya da secilebiliyor.
Karisik girdi kabul ediliyor cunku kullanicinin elinde genelde ikisi birden var.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..source.file_source import MEDIA_SUFFIXES

_PLACEHOLDER = (
    "https://www.youtube.com/watch?v=...\n"
    "https://www.youtube.com/playlist?list=...\n"
    "C:\\videolar\\sunum.mp4"
)


class AddDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Kuyruğa ekle")
        self.setMinimumSize(620, 340)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Her satıra bir YouTube adresi veya dosya yolu yazın. "
            "Playlist adresleri tek tek videolara açılır."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(_PLACEHOLDER)
        self.editor.setPlainText(initial)
        layout.addWidget(self.editor, 1)

        row = QHBoxLayout()
        browse = QPushButton("Dosya seç...")
        browse.clicked.connect(self._browse_files)
        row.addWidget(browse)

        browse_dir = QPushButton("Klasör seç...")
        browse_dir.clicked.connect(self._browse_dir)
        row.addWidget(browse_dir)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("Kuyruğa ekle")
        ok_button.setProperty("primary", True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _append(self, lines: list[str]) -> None:
        if not lines:
            return
        current = self.editor.toPlainText().rstrip()
        joined = "\n".join(lines)
        self.editor.setPlainText(f"{current}\n{joined}" if current else joined)

    def _browse_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(MEDIA_SUFFIXES))
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Video veya ses dosyaları",
            "",
            f"Medya dosyaları ({patterns});;Tüm dosyalar (*)",
        )
        self._append(list(files))

    def _browse_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Medya klasörü")
        if directory:
            self._append([directory])

    def raw_text(self) -> str:
        return self.editor.toPlainText()
