"""Верстка PDF-видання «Глаголичні новини».

Основний текст набирається шрифтом Galabir (кирилиця → глаголиця),
під кожним блоком іде паралельний текст українською: менший, світло-сірий,
стандартним шрифтом (DejaVu Sans).
"""
import os
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, KeepTogether,
                                PageTemplate, Paragraph, Spacer)
from fontTools.ttLib import TTFont as FTFont
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
GALABIR_PATH = os.path.join(HERE, "fonts", "Galabir-Light.ttf")
STANDARD_PATH = os.path.join(HERE, "fonts", "DejaVuSans.ttf")

pdfmetrics.registerFont(TTFont("Galabir", GALABIR_PATH))
pdfmetrics.registerFont(TTFont("Standard", STANDARD_PATH))

_GALABIR_CMAP = set(FTFont(GALABIR_PATH).getBestCmap().keys())
_REPLACE = {"\u00a0": " ", "\u2009": " ", "\u200b": "", "…": "...", "‘": "’", "‚": ","}

INK = HexColor("#14213D")
GOLD = HexColor("#B08D4A")
GREY = HexColor("#A6A6A6")        # світло-сірий для паралельного тексту
RULE = HexColor("#D9D2C3")

MONTHS_UK = ["січня", "лютого", "березня", "квітня", "травня", "червня",
             "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def galabir_safe(text):
    """Лишає лише символи, які є в шрифті Galabir (щоб не було порожніх квадратів)."""
    out = []
    for ch in text or "":
        ch = _REPLACE.get(ch, ch)
        out.extend(c for c in ch if ord(c) in _GALABIR_CMAP or c == "\n")
    return "".join(out)


def _styles():
    return {
        "masthead": ParagraphStyle("masthead", fontName="Galabir", fontSize=44, leading=48,
                                   textColor=INK, alignment=TA_LEFT),
        "masthead_uk": ParagraphStyle("masthead_uk", fontName="Standard", fontSize=8.5,
                                      leading=11, textColor=GREY, spaceAfter=2),
        "dateline": ParagraphStyle("dateline", fontName="Galabir", fontSize=13, leading=16,
                                   textColor=GOLD),
        "dateline_uk": ParagraphStyle("dateline_uk", fontName="Standard", fontSize=7.5,
                                      leading=10, textColor=GREY),
        "num": ParagraphStyle("num", fontName="Galabir", fontSize=11, leading=13, textColor=GOLD),
        "h": ParagraphStyle("h", fontName="Galabir", fontSize=19, leading=23, textColor=INK,
                            spaceBefore=2),
        "h_uk": ParagraphStyle("h_uk", fontName="Standard", fontSize=8, leading=10.5,
                               textColor=GREY, spaceAfter=5),
        "lead": ParagraphStyle("lead", fontName="Galabir", fontSize=12, leading=16.5,
                               textColor=INK),
        "lead_uk": ParagraphStyle("lead_uk", fontName="Standard", fontSize=7.5, leading=10,
                                  textColor=GREY, spaceAfter=4),
        "src": ParagraphStyle("src", fontName="Standard", fontSize=6.5, leading=9, textColor=GOLD),
    }


def _page_decor(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(20 * mm, 14 * mm, w - 20 * mm, 14 * mm)
    canvas.setFont("Galabir", 9)
    canvas.setFillColor(INK)
    canvas.drawString(20 * mm, 9 * mm, galabir_safe("Глаголичні новини"))
    canvas.setFont("Standard", 6.5)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, 5.5 * mm, "Глаголичні новини · шрифт Galabir")
    canvas.setFont("Standard", 7)
    canvas.drawRightString(w - 20 * mm, 7 * mm, str(doc.page))
    canvas.restoreState()


def build_edition_pdf(items, out_path, date=None):
    """items: [{'title_uk','summary_uk','source','link'}, ...] — уже українською."""
    date = date or datetime.now()
    date_uk = f"{date.day} {MONTHS_UK[date.month - 1]} {date.year}"
    st = _styles()

    doc = BaseDocTemplate(out_path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=18 * mm, bottomMargin=20 * mm,
                          title="Глаголичні новини", author="Глаголичні новини")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=_page_decor)])

    story = [
        Paragraph(escape(galabir_safe("Глаголичні новини")), st["masthead"]),
        Paragraph("Глаголичні новини — щоденне видання", st["masthead_uk"]),
        HRFlowable(width="100%", thickness=1.4, color=INK, spaceBefore=4, spaceAfter=5),
        Paragraph(escape(galabir_safe(f"Випуск за {date_uk}")), st["dateline"]),
        Paragraph(escape(f"Випуск за {date_uk}"), st["dateline_uk"]),
        Spacer(1, 10),
    ]

    if not items:
        story.append(Paragraph(escape(galabir_safe("Сьогодні свіжих новин не знайдено.")), st["lead"]))
        story.append(Paragraph("Сьогодні свіжих новин не знайдено.", st["lead_uk"]))
    for i, it in enumerate(items, start=1):
        title, lead = it["title_uk"], it.get("summary_uk", "")
        block = [
            HRFlowable(width="100%", thickness=0.5, color=RULE, spaceBefore=4, spaceAfter=7),
            Paragraph(escape(galabir_safe(f"№ {i}")), st["num"]),
            Paragraph(escape(galabir_safe(title)), st["h"]),
            Paragraph(escape(title), st["h_uk"]),
        ]
        if lead:
            block += [Paragraph(escape(galabir_safe(lead)), st["lead"]),
                      Paragraph(escape(lead), st["lead_uk"])]
        src = escape(it["source"])
        link = escape(it.get("link", ""))
        block.append(Paragraph(f'{src} · <link href="{link}">{link}</link>', st["src"]))
        block.append(Spacer(1, 6))
        story.append(KeepTogether(block))

    doc.build(story)
    return out_path
