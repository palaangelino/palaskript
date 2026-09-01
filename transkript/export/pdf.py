"""PDF disa aktarimi (ReportLab Platypus).

Konusma videolari icin okunabilir bir belge uretmek bu dosyanin tek isi:

- Kapak: videonun basligi, kanali, adresi ve uretim bilgileri. Transkriptin
  nereden geldigi belgenin icinde kayitli kaliyor.
- Icindekiler: bolum baslikları ve sayfa numaralari.
- PDF yer imleri: okuyucunun kenar cubugundan bolumlere atlanabiliyor. 90
  sayfalik bir belgede kaydirarak gezmek ise yaramiyor.

Sayfa numaralarinin dogru cikmasi icin belge iki gecis halinde uretiliyor
(multiBuild): ilk gecis bolumlerin hangi sayfaya dustugunu ogreniyor, ikincisi
icindekileri o bilgiyle yaziyor.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from ..chapters import assign_paragraphs, format_timestamp
from ..config import Settings
from ..datatypes import TranscriptDoc
from . import fonts

PAGE_SIZE = A4
MARGIN = 2 * cm

_TIMESTAMP_HEX = "#8A8A8A"
_TIMESTAMP_COLOR = colors.HexColor(_TIMESTAMP_HEX)
_RULE_COLOR = colors.HexColor("#D0D0D0")
_META_LABEL_COLOR = colors.HexColor("#666666")


def _esc(text: str) -> str:
    """Platypus mini-HTML ayristiricisi icin kacis.

    Transkript metninde & veya < gecebiliyor; kacislanmazsa ReportLab
    ayristirma hatasi verip tum belgeyi patlatiyor.
    """
    return escape(text)


class ChapterHeading(Paragraph):
    """Yer imi anahtarini tasiyan baslik.

    Anahtar sayacla degil bolumun kendi zamanindan uretiliyor: multiBuild
    hikayeyi iki kez isliyor ve sayac kullanilsa ikinci geciste anahtarlar
    kayardi.
    """

    def __init__(self, text: str, style: ParagraphStyle, bookmark_key: str) -> None:
        super().__init__(text, style)
        self.bookmark_key = bookmark_key


class TranscriptTemplate(BaseDocTemplate):
    def __init__(self, path: str, *, header_text: str, **kwargs: object) -> None:
        super().__init__(path, pagesize=PAGE_SIZE, **kwargs)
        self.header_text = header_text

        frame = Frame(
            MARGIN,
            MARGIN,
            PAGE_SIZE[0] - 2 * MARGIN,
            PAGE_SIZE[1] - 2 * MARGIN,
            id="body",
        )
        cover_frame = Frame(
            MARGIN,
            MARGIN,
            PAGE_SIZE[0] - 2 * MARGIN,
            PAGE_SIZE[1] - 2 * MARGIN,
            id="cover",
        )
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[cover_frame]),
                PageTemplate(id="body", frames=[frame], onPage=self._decorate),
            ]
        )

    def _decorate(self, canvas, doc) -> None:  # noqa: ANN001 - ReportLab imzasi
        choice = fonts.register()
        canvas.saveState()
        canvas.setFont(choice.regular, 8)
        canvas.setFillColor(_META_LABEL_COLOR)

        top = PAGE_SIZE[1] - MARGIN + 0.45 * cm
        title = self.header_text
        if len(title) > 78:
            title = title[:75] + "..."
        canvas.drawString(MARGIN, top, title)
        canvas.drawRightString(PAGE_SIZE[0] - MARGIN, top, str(canvas.getPageNumber()))

        canvas.setStrokeColor(_RULE_COLOR)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, top - 0.15 * cm, PAGE_SIZE[0] - MARGIN, top - 0.15 * cm)
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:  # noqa: ANN001 - ReportLab imzasi
        if isinstance(flowable, ChapterHeading):
            text = flowable.getPlainText()
            key = flowable.bookmark_key
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0, closed=False)
            self.notify("TOCEntry", (0, text, self.page, key))


def _styles() -> dict[str, ParagraphStyle]:
    choice = fonts.register()
    base = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "TranskriptTitle",
            parent=base["Title"],
            fontName=choice.bold,
            fontSize=20,
            leading=25,
            alignment=0,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "TranskriptSubtitle",
            parent=base["Normal"],
            fontName=choice.regular,
            fontSize=11,
            leading=15,
            textColor=_META_LABEL_COLOR,
            spaceAfter=18,
        ),
        "meta": ParagraphStyle(
            "TranskriptMeta",
            parent=base["Normal"],
            fontName=choice.regular,
            fontSize=9.5,
            leading=13,
        ),
        "metaLabel": ParagraphStyle(
            "TranskriptMetaLabel",
            parent=base["Normal"],
            fontName=choice.regular,
            fontSize=9.5,
            leading=13,
            textColor=_META_LABEL_COLOR,
        ),
        "tocTitle": ParagraphStyle(
            "TranskriptTocTitle",
            parent=base["Heading1"],
            fontName=choice.bold,
            fontSize=15,
            leading=20,
            spaceAfter=12,
        ),
        "chapter": ParagraphStyle(
            "ChapterHeading",
            parent=base["Heading2"],
            fontName=choice.bold,
            fontSize=13.5,
            leading=18,
            spaceBefore=20,
            spaceAfter=8,
            keepWithNext=1,
        ),
        "body": ParagraphStyle(
            "TranskriptBodyText",
            parent=base["Normal"],
            fontName=choice.regular,
            fontSize=10.5,
            leading=15.5,
            alignment=TA_JUSTIFY,
            spaceAfter=9,
        ),
        "toc1": ParagraphStyle(
            "TranskriptToc1",
            parent=base["Normal"],
            fontName=choice.regular,
            fontSize=10.5,
            leading=17,
            leftIndent=0,
        ),
    }


def _cover(doc: TranscriptDoc, styles: dict[str, ParagraphStyle]) -> list:
    src = doc.source
    story: list = [Spacer(1, 2.5 * cm), Paragraph(_esc(src.title), styles["title"])]

    if src.channel:
        story.append(Paragraph(_esc(src.channel), styles["subtitle"]))
    else:
        story.append(Spacer(1, 0.6 * cm))

    rows: list[list] = []

    def add(label: str, value: str | None) -> None:
        if value:
            rows.append(
                [
                    Paragraph(_esc(label), styles["metaLabel"]),
                    Paragraph(_esc(value), styles["meta"]),
                ]
            )

    add("Kaynak", src.url)
    if src.upload_date and len(src.upload_date) == 8:
        d = src.upload_date
        add("Yayin tarihi", f"{d[6:8]}.{d[4:6]}.{d[0:4]}")
    add("Sure", format_timestamp(src.duration, always_hours=True))
    add("Uretim tarihi", doc.created_at.strftime("%d.%m.%Y %H:%M"))
    add("Kaynak", doc.model_name)
    if doc.languages:
        add("Algilanan dil", ", ".join(doc.languages))
    add("Kelime sayisi", f"{doc.word_count:,}".replace(",", "."))
    if doc.chapters:
        origin = "video bolumleri" if doc.chapters[0].origin == "youtube" else "zamana gore"
        add("Bolum", f"{len(doc.chapters)} ({origin})")

    table = Table(rows, colWidths=[3.6 * cm, PAGE_SIZE[0] - 2 * MARGIN - 3.6 * cm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(table)

    if doc.from_subtitles:
        story.append(Spacer(1, 0.8 * cm))
        story.append(
            Paragraph(
                "Bu belge videonun kendi altyazisindan uretildi, ses yeniden yazilmadi.",
                styles["metaLabel"],
            )
        )
    return story


def _body(doc: TranscriptDoc, settings: Settings, styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    groups = assign_paragraphs(doc.paragraphs, doc.chapters)
    interval = max(1, settings.timestamp_interval_minutes) * 60
    next_stamp = 0.0

    for chapter, paragraphs in groups:
        if chapter is not None:
            label = (
                f"{format_timestamp(chapter.start, always_hours=True)}"
                f"&nbsp;&nbsp;{_esc(chapter.title)}"
            )
            story.append(
                ChapterHeading(label, styles["chapter"], f"ch-{int(chapter.start)}")
            )
            next_stamp = chapter.start + interval

        for para in paragraphs:
            stamp = ""
            if settings.timestamp_mode == "paragraph":
                stamp = format_timestamp(para.start, always_hours=True)
            elif settings.timestamp_mode == "interval" and para.start >= next_stamp:
                stamp = format_timestamp(para.start, always_hours=True)
                next_stamp = para.start + interval

            text = _esc(para.text)
            if stamp:
                text = f'<font color="{_TIMESTAMP_HEX}" size="8">[{stamp}]</font> ' + text
            story.append(Paragraph(text, styles["body"]))

    if not story:
        story.append(Paragraph("Bu videoda yaziya dokulebilecek konusma bulunamadi.", styles["body"]))
    return story


def write(doc: TranscriptDoc, path: Path, settings: Settings) -> Path:
    """Belgeyi PDF olarak yaz ve yolunu dondur."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fonts.register()
    styles = _styles()

    template = TranscriptTemplate(
        str(path),
        header_text=doc.source.title,
        title=doc.source.title,
        author=doc.source.channel or "Transkript",
        subject="Video transkripti",
        creator="Transkript",
    )

    story: list = [NextPageTemplate("body")]
    story.extend(_cover(doc, styles))
    story.append(PageBreak())

    use_toc = bool(doc.chapters)
    if use_toc:
        toc = TableOfContents()
        toc.levelStyles = [styles["toc1"]]
        toc.dotsMinLevel = 0
        story.append(Paragraph("Icindekiler", styles["tocTitle"]))
        story.append(toc)
        story.append(PageBreak())

    story.extend(_body(doc, settings, styles))

    if use_toc:
        # Iki gecis: ilk gecis sayfa numaralarini ogreniyor, ikincisi yaziyor.
        template.multiBuild(story)
    else:
        template.build(story)
    return path
