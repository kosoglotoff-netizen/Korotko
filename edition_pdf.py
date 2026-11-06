"""Верстка PDF-видання «Глаголичні новини» у вигляді мобільної новинної стрічки.

Сторінка має пропорції телефона (390 × 844 pt ≈ CSS-viewport смартфона), тож при
відкритті на телефоні 1 pt ≈ 1 px, як на мобільному сайті. Основний текст
набирається шрифтом Galabir (кирилиця → глаголиця); під кожним блоком — паралельний
український текст: менший, світло-сірий, стандартним шрифтом (DejaVu Sans).
"""
import os
from datetime import datetime
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont as FTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, KeepTogether,
                                NextPageTemplate, PageTemplate, Paragraph, Spacer)

HERE = os.path.dirname(os.path.abspath(__file__))
GALABIR_PATH = os.path.join(HERE, "fonts", "Galabir-Light.ttf")
STANDARD_PATH = os.path.join(HERE, "fonts", "DejaVuSans.ttf")

pdfmetrics.registerFont(TTFont("Galabir", GALABIR_PATH))
pdfmetrics.registerFont(TTFont("Standard", STANDARD_PATH))

_GALABIR_CMAP = set(FTFont(GALABIR_PATH).getBestCmap().keys())
_REPLACE = {"\u00a0": " ", "\u2009": " ", "\u200b": "", "…": "...", "‘": "’", "‚": ","}

# --- мобільна сторінка ---
PAGE_W, PAGE_H = 390, 844
MARGIN = 16
HEADER_H = 150          # висота темної шапки на першій сторінці
FOOTER_H = 34

NAVY = HexColor("#14213D")
INK = HexColor("#14213D")
GOLD = HexColor("#B08D4A")
GOLD_LIGHT = HexColor("#D8B97A")
GREY = HexColor("#A6A6A6")          # світло-сірий паралельний текст
GREY_ON_NAVY = HexColor("#B9C0CE")
RULE = HexColor("#E3DDD0")

MONTHS_UK = ["січня", "лютого", "березня", "квітня", "травня", "червня",
             "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def galabir_safe(text):
    """Лишає лише символи, які є в Galabir (щоб не було порожніх квадратів)."""
    out = []
    for ch in text or "":
        ch = _REPLACE.get(ch, ch)
        out.extend(c for c in ch if ord(c) in _GALABIR_CMAP or c == "\n")
    return "".join(out)


def _styles():
    return {
        "num": ParagraphStyle("num", fontName="Galabir", fontSize=18, leading=22, textColor=GOLD),
        "h": ParagraphStyle("h", fontName="Galabir", fontSize=30, leading=37, textColor=INK,
                            alignment=TA_LEFT, spaceBefore=2),
        "h_uk": ParagraphStyle("h_uk", fontName="Standard", fontSize=14, leading=19,
                               textColor=GREY, spaceAfter=10),
        "lead": ParagraphStyle("lead", fontName="Galabir", fontSize=22, leading=31, textColor=INK),
        "lead_uk": ParagraphStyle("lead_uk", fontName="Standard", fontSize=13.5, leading=19,
                                  textColor=GREY, spaceAfter=8),
        "src": ParagraphStyle("src", fontName="Standard", fontSize=11, leading=15, textColor=GOLD),
        "empty": ParagraphStyle("empty", fontName="Galabir", fontSize=22, leading=30, textColor=INK),
    }


def _fit_size(text, font, max_width, start, minimum=14):
    size = start
    while size > minimum and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _make_page_callbacks(date_uk):
    glag_title = galabir_safe("Глаголичні новини")
    glag_date = galabir_safe(date_uk)

    def footer(canvas, doc):
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, FOOTER_H - 6, PAGE_W - MARGIN, FOOTER_H - 6)
        canvas.setFont("Galabir", 13)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN, 11, glag_title)
        canvas.setFont("Standard", 10)
        canvas.setFillColor(GREY)
        canvas.drawRightString(PAGE_W - MARGIN, 12, str(doc.page))

    def first_page(canvas, doc):
        canvas.saveState()
        # темна шапка, як у мобільному сайті
        canvas.setFillColor(NAVY)
        canvas.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, stroke=0, fill=1)
        canvas.setFillColor(GOLD_LIGHT)
        canvas.rect(0, PAGE_H - HEADER_H - 3, PAGE_W, 3, stroke=0, fill=1)

        max_w = PAGE_W - 2 * MARGIN
        size = _fit_size(glag_title, "Galabir", max_w, 46)
        canvas.setFillColor(HexColor("#F3E9D2"))
        canvas.setFont("Galabir", size)
        canvas.drawString(MARGIN, PAGE_H - 62, glag_title)

        canvas.setFont("Standard", 12)
        canvas.setFillColor(GREY_ON_NAVY)
        canvas.drawString(MARGIN, PAGE_H - 84, "Глаголичні новини — щоденне видання")

        canvas.setFont("Galabir", 20)
        canvas.setFillColor(GOLD_LIGHT)
        canvas.drawString(MARGIN, PAGE_H - 116, glag_date)
        canvas.setFont("Standard", 11)
        canvas.setFillColor(GREY_ON_NAVY)
        canvas.drawString(MARGIN, PAGE_H - 134, f"Випуск за {date_uk}")
        canvas.restoreState()
        footer(canvas, doc)

    return first_page, footer


def build_edition_pdf(items, out_path, date=None):
    """items: [{'title_uk','summary_uk','source','link'}, ...] — уже українською."""
    date = date or datetime.now()
    date_uk = f"{date.day} {MONTHS_UK[date.month - 1]} {date.year}"
    st = _styles()
    first_page, later_page = _make_page_callbacks(date_uk)

    doc = BaseDocTemplate(out_path, pagesize=(PAGE_W, PAGE_H),
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=FOOTER_H + 6,
                          title="Глаголичні новини", author="Глаголичні новини")
    pad = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    width = PAGE_W - 2 * MARGIN
    frame_first = Frame(MARGIN, FOOTER_H + 6, width, PAGE_H - HEADER_H - 3 - 14 - FOOTER_H - 6,
                        id="first", **pad)
    frame_later = Frame(MARGIN, FOOTER_H + 6, width, PAGE_H - MARGIN - FOOTER_H - 6,
                        id="later", **pad)
    doc.addPageTemplates([
        PageTemplate(id="first", frames=[frame_first], onPage=first_page),
        PageTemplate(id="later", frames=[frame_later], onPage=later_page),
    ])

    story = [NextPageTemplate("later")]

    if not items:
        story.append(Paragraph(escape(galabir_safe("Сьогодні свіжих новин не знайдено.")), st["empty"]))
        story.append(Paragraph("Сьогодні свіжих новин не знайдено.", st["lead_uk"]))

    for i, it in enumerate(items, start=1):
        title, lead = it["title_uk"], it.get("summary_uk", "")
        # заголовок із номером — разом; лід може переходити на наступну сторінку
        story.append(KeepTogether([
            Paragraph(escape(galabir_safe(f"№ {i}")), st["num"]),
            Paragraph(escape(galabir_safe(title)), st["h"]),
            Paragraph(escape(title), st["h_uk"]),
        ]))
        if lead:
            story.append(Paragraph(escape(galabir_safe(lead)), st["lead"]))
            story.append(Paragraph(escape(lead), st["lead_uk"]))
        src = escape(it["source"])
        link = escape(it.get("link", ""))
        story.append(Paragraph(f'{src} · <link href="{link}">читати оригінал →</link>', st["src"]))
        story.append(HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=14, spaceAfter=14))

    doc.build(story)
    return out_path
