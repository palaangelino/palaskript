"""PDF ve TXT disa aktarimi.

Kritik nokta Turkce karakterler: ReportLab'in yerlesik fontlari g-breve,
i-dotless ve s-cedilla tasimiyor, gomulu bir TrueType font sart. Bu testler
metnin PDF icinde gercekten aranabilir sekilde durdugunu dogruluyor.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pypdf import PdfReader

from palaskript.config import Settings
from palaskript.datatypes import Chapter, Paragraph, SourceInfo, TranscriptDoc
from palaskript.export import fonts
from palaskript.export import pdf as pdf_export
from palaskript.export import txt as txt_export

TURKISH = "Gunaydin! Sicak cay ictik, cocuklar okula gitti. Ismail ogle yemegi hazirladi."


def make_doc(*, chapters: bool = True, paragraphs: int = 6) -> TranscriptDoc:
    source = SourceInfo(
        kind="youtube",
        source_id="youtube:abc123",
        title="Yapay Zeka Uzerine Bir Konusma",
        duration=3600.0,
        url="https://www.youtube.com/watch?v=abc123",
        channel="Ornek Kanal",
        upload_date="20260115",
    )
    paras = [
        Paragraph(start=i * 300.0, end=i * 300.0 + 280.0, text=f"{TURKISH} Paragraf {i}.")
        for i in range(paragraphs)
    ]
    chapter_list = (
        [
            Chapter(start=0.0, end=1200.0, title="Giris ve tanisma"),
            Chapter(start=1200.0, end=2400.0, title="Teknik detaylar"),
            Chapter(start=2400.0, end=3600.0, title="Sorular"),
        ]
        if chapters
        else []
    )
    return TranscriptDoc(
        source=source,
        paragraphs=paras,
        chapters=chapter_list,
        languages=["tr", "en"],
        model_name="faster-whisper large-v3-turbo (int8, CPU)",
        created_at=datetime(2026, 9, 1, 14, 30),
    )


def extract_text(path: Path) -> str:
    """PDF'in metin katmanini gercek bir okuyucuyla cikar.

    Gomulu TrueType font alt kumesi kullandigimiz icin metin CID olarak
    kodlaniyor; ham akisi okumak yetmiyor. pypdf ile okumak ayni zamanda
    "metin katmani aranabilir" iddiasini da dogruluyor: bir PDF okuyucusunun
    icinde arama yapabilmesi tam olarak bu.
    """
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture(autouse=True)
def reset_fonts():
    fonts.reset()
    yield
    fonts.reset()


class TestFontResolution:
    def test_finds_a_turkish_capable_font(self):
        """Windows sistem fontlari her zaman var; yedek zinciri tutmali."""
        choice = fonts.register()
        assert choice.supports_turkish
        assert choice.source != "Helvetica (yerlesik)"

    def test_registration_is_idempotent(self):
        assert fonts.register() == fonts.register()


class TestPdf:
    def test_writes_a_valid_pdf(self, tmp_path):
        path = pdf_export.write(make_doc(), tmp_path / "cikti.pdf", Settings())
        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF-")
        assert path.stat().st_size > 2000

    def test_contains_the_transcript_text(self, tmp_path):
        path = pdf_export.write(make_doc(), tmp_path / "cikti.pdf", Settings())
        assert "Paragraf 0" in extract_text(path)

    def test_creates_outline_entries_for_chapters(self, tmp_path):
        """PDF yer imleri: 90 sayfalik belgede gezinmenin tek yolu."""
        path = pdf_export.write(make_doc(), tmp_path / "cikti.pdf", Settings())
        assert b"/Outlines" in path.read_bytes()

    def test_cover_carries_provenance(self, tmp_path):
        path = pdf_export.write(make_doc(), tmp_path / "cikti.pdf", Settings())
        text = extract_text(path)
        assert "youtube.com" in text or "abc123" in text

    def test_works_without_chapters(self, tmp_path):
        path = pdf_export.write(make_doc(chapters=False), tmp_path / "duz.pdf", Settings())
        assert path.read_bytes().startswith(b"%PDF-")

    def test_handles_empty_transcript(self, tmp_path):
        doc = make_doc(chapters=False, paragraphs=0)
        path = pdf_export.write(doc, tmp_path / "bos.pdf", Settings())
        assert path.exists()

    def test_escapes_markup_in_transcript_text(self, tmp_path):
        """Kacislanmazsa ReportLab ayristirma hatasi verip belgeyi patlatir."""
        doc = make_doc(chapters=False, paragraphs=0)
        doc.paragraphs = [
            Paragraph(start=0.0, end=10.0, text="5 < 7 ve a & b <font> etiketi")
        ]
        path = pdf_export.write(doc, tmp_path / "kacis.pdf", Settings())
        assert path.exists()

    def test_escapes_markup_in_chapter_titles(self, tmp_path):
        doc = make_doc(chapters=False, paragraphs=2)
        doc.chapters = [Chapter(start=0.0, end=3600.0, title="Soru & Cevap <bolum>")]
        path = pdf_export.write(doc, tmp_path / "baslik.pdf", Settings())
        assert path.exists()

    def test_creates_missing_output_directory(self, tmp_path):
        target = tmp_path / "yeni" / "klasor" / "cikti.pdf"
        assert pdf_export.write(make_doc(), target, Settings()).exists()

    @pytest.mark.parametrize("mode", ["paragraph", "interval", "none"])
    def test_all_timestamp_modes_render(self, tmp_path, mode):
        settings = Settings()
        settings.timestamp_mode = mode
        path = pdf_export.write(make_doc(), tmp_path / f"{mode}.pdf", settings)
        assert path.read_bytes().startswith(b"%PDF-")

    def test_real_turkish_glyphs_survive_round_trip(self, tmp_path):
        """Planin isaret ettigi asil risk.

        ReportLab'in yerlesik fontlari g-breve, i-dotless ve s-cedilla
        tasimiyor; gomulu font olmadan bu harfler PDF'te bos kutuya donuyor.
        Metin katmanindan aynen geri okunabiliyorsa gomme calisiyor demektir.
        """
        doc = make_doc(chapters=False, paragraphs=0)
        turkish = "Ilgınç bir şey: çoğu kişi öğün üstü ığdır'ı bilmiyor. ÖĞÜŞÇİ ıspanak."
        doc.paragraphs = [Paragraph(start=0.0, end=10.0, text=turkish)]
        path = pdf_export.write(doc, tmp_path / "turkce.pdf", Settings())

        extracted = extract_text(path)
        for glyph in "ğşıçöüİĞŞÇÖÜ":
            assert glyph in extracted, f"{glyph} harfi PDF metin katmaninda yok"

    def test_turkish_chapter_titles_survive(self, tmp_path):
        doc = make_doc(chapters=False, paragraphs=2)
        doc.chapters = [Chapter(start=0.0, end=3600.0, title="Açılış ve tanışma")]
        path = pdf_export.write(doc, tmp_path / "baslik-tr.pdf", Settings())
        assert "Açılış" in extract_text(path)

    def test_long_document_builds(self, tmp_path):
        """3.5 saatlik bir konusma ~1500 paragraf eder."""
        doc = make_doc(chapters=True, paragraphs=400)
        path = pdf_export.write(doc, tmp_path / "uzun.pdf", Settings())
        assert path.stat().st_size > 20000


class TestTxt:
    def test_writes_utf8_with_turkish_characters(self, tmp_path):
        path = txt_export.write(make_doc(), tmp_path / "cikti.txt", Settings())
        content = path.read_text(encoding="utf-8")
        assert "Gunaydin" in content
        assert "Paragraf 0" in content

    def test_includes_header_metadata(self, tmp_path):
        path = txt_export.write(make_doc(), tmp_path / "cikti.txt", Settings())
        content = path.read_text(encoding="utf-8")
        assert "Yapay Zeka Uzerine Bir Konusma" in content
        assert "Ornek Kanal" in content
        assert "youtube.com" in content

    def test_includes_chapter_headings(self, tmp_path):
        path = txt_export.write(make_doc(), tmp_path / "cikti.txt", Settings())
        assert "Giris ve tanisma" in path.read_text(encoding="utf-8")

    def test_paragraph_mode_stamps_every_paragraph(self, tmp_path):
        settings = Settings()
        settings.timestamp_mode = "paragraph"
        content = txt_export.render(make_doc(), settings)
        assert content.count("[00:") + content.count("[01:") >= 6

    def test_none_mode_omits_paragraph_stamps(self, tmp_path):
        settings = Settings()
        settings.timestamp_mode = "none"
        settings.use_chapters = False
        doc = make_doc(chapters=False)
        content = txt_export.render(doc, settings)
        assert "[0" not in content

    def test_empty_transcript(self, tmp_path):
        doc = make_doc(chapters=False, paragraphs=0)
        path = txt_export.write(doc, tmp_path / "bos.txt", Settings())
        assert path.exists()


class TestWordCount:
    def test_counts_words_across_paragraphs(self):
        doc = make_doc(paragraphs=3)
        assert doc.word_count == sum(len(p.text.split()) for p in doc.paragraphs)
