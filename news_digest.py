#!/usr/bin/env python3
"""
Щоденний дайджест світових новин у Telegram — глаголицею (шрифт Galabir).

Бере кілька надійних RSS-стрічок, витягує лід кожної статті, відфільтровує
спорт/шоубізнес/кримінал/локальні трагедії, перекладає українською
(безкоштовно, без API-ключа) і рендерить дайджест як зображення шрифтом
Galabir (авторська "глаголична" стилізація кирилиці), яке надсилається в
Telegram. Посилання на джерела йдуть окремим текстовим повідомленням під
картинкою (щоб лишались клікабельними).

Змінні середовища (GitHub Secrets):
    TELEGRAM_BOT_TOKEN  — токен бота від @BotFather
    TELEGRAM_CHAT_ID    — ID чату/каналу, куди слати повідомлення
"""

import os
import re
import sys
import time
import html
from datetime import datetime, timezone, timedelta

import feedparser
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator, MyMemoryTranslator
from PIL import Image, ImageDraw, ImageFont

# --- Джерела новин: великі, надійні агенції зі світовим охопленням ---
FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
]

MAX_ITEMS = 8
MAX_AGE_HOURS = 30
LEAD_MAX_CHARS = 400

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Galabir_04.ttf")
IMAGE_WIDTH = 1080
MARGIN = 50
TITLE_SIZE = 34
BODY_SIZE = 28
LINE_SPACING = 10
BLOCK_SPACING = 34

# --- Ключові слова для фільтрації небажаних категорій ---
SPORT_KEYWORDS = [
    "football", "soccer", "nba", "nfl", "nhl", "mlb", "tennis", "golf",
    "cricket", "rugby", "olympic", "olympics", "athlete", "match", "tournament",
    "championship", "world cup", "premier league", "la liga", "bundesliga",
    "serie a", "champions league", "wimbledon", "grand slam", "formula 1",
    " f1 ", "boxing", "ufc", "mma", "medal", "coach", "stadium", "playoffs",
    "goalkeeper", "midfielder", "striker", "referee", "world series",
    "super bowl", "grand prix", "marathon", "cyclist", "cycling", "sport",
]

ENTERTAINMENT_KEYWORDS = [
    "celebrity", "actor ", "actress", "singer", "album", "premiere",
    "red carpet", "hollywood", "grammy", "oscar", "oscars", "cannes",
    "box office", "tv show", "reality tv", "kardashian", "pop star",
    "music video", "film festival", "movie review", "royal wedding",
    "engaged to", "divorce from", "dating rumors", "influencer",
]

CRIME_KEYWORDS = [
    "murder", "shooting at", "stabbing", "stabbed", "arrested for",
    "convicted", "sentenced to", "on trial for", "robbery", "kidnap",
    "burglary", "assault on", "domestic violence", "serial killer",
    "manhunt", "gunman", "hostage situation", "police say", "suspect in",
]

LOCAL_TRAGEDY_KEYWORDS = [
    "nursing home", "care home", "retirement home", "house fire",
    "residential fire", "apartment fire", "car crash", "road accident",
    "traffic accident", "building collapse", "gas explosion",
    "drowned", "drowning", "avalanche kills",
]

EXCLUDE_KEYWORDS = SPORT_KEYWORDS + ENTERTAINMENT_KEYWORDS + CRIME_KEYWORDS + LOCAL_TRAGEDY_KEYWORDS


def is_excluded(title, summary, categories):
    text = f"{title} {summary}".lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return True
    for cat in categories:
        cat_low = cat.lower()
        if any(tag in cat_low for tag in ("sport", "entertainment", "showbiz", "celebrity")):
            return True
    return False


def clean_html(raw_html):
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def fetch_all_items():
    items = []
    for source_name, url in FEEDS:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"[WARN] Не вдалося отримати {source_name}: {e}", file=sys.stderr)
            continue

        for entry in parsed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_dt = datetime(*published[:6], tzinfo=timezone.utc) if published else datetime.now(timezone.utc)

            categories = [t.get("term", "") for t in entry.get("tags", [])] if entry.get("tags") else []
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = clean_html(summary_raw)[:LEAD_MAX_CHARS]
            title = entry.get("title", "").strip()

            if is_excluded(title, summary, categories):
                continue

            items.append({
                "source": source_name,
                "title": title,
                "summary": summary,
                "link": entry.get("link", "").strip(),
                "published": pub_dt,
            })
    return items


def filter_and_rank(items):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)

    fresh = [i for i in items if i["published"] >= cutoff]
    fresh.sort(key=lambda i: i["published"], reverse=True)

    seen_titles = set()
    unique = []
    for item in fresh:
        key = item["title"].lower()[:60]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(item)

    return unique[:MAX_ITEMS]


_ERROR_MARKERS = ("error 500", "that\u2019s an error", "that's an error", "please try again later")


def _looks_like_error(text):
    if not text:
        return True
    low = text.lower()
    return any(marker in low for marker in _ERROR_MARKERS)


def translate_text(text, retries=3, base_delay=2.0):
    if not text:
        return text
    for attempt in range(retries):
        try:
            result = GoogleTranslator(source="auto", target="uk").translate(text)
            if result and not _looks_like_error(result):
                return result
        except Exception as e:
            print(f"[WARN] GoogleTranslator спроба {attempt + 1} не вдалася: {e}", file=sys.stderr)
        time.sleep(base_delay * (attempt + 1))

    try:
        chunk = text[:490]
        result = MyMemoryTranslator(source="en-GB", target="uk-UA").translate(chunk)
        if result and not _looks_like_error(result):
            return result
    except Exception as e:
        print(f"[WARN] MyMemoryTranslator також не вдався: {e}", file=sys.stderr)

    print("[WARN] Переклад не вдався, лишаю оригінал англійською.", file=sys.stderr)
    return text


def translate_item(title, summary):
    if not summary:
        return translate_text(title), ""

    combined = f"{title}\n{summary}"
    translated = translate_text(combined)

    if "\n" in translated:
        parts = translated.split("\n", 1)
        return parts[0].strip(), parts[1].strip()

    return translate_text(title), translate_text(summary)


# --- Рендеринг дайджесту як зображення шрифтом Galabir ---

def _wrap_text(draw, text, font, max_width):
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_digest_image(items, date_str, out_path):
    title_font = ImageFont.truetype(FONT_PATH, TITLE_SIZE)
    body_font = ImageFont.truetype(FONT_PATH, BODY_SIZE)

    max_text_width = IMAGE_WIDTH - 2 * MARGIN

    # Спершу міряємо висоту на тимчасовому канвасі
    tmp_img = Image.new("RGB", (IMAGE_WIDTH, 10), "white")
    tmp_draw = ImageDraw.Draw(tmp_img)

    blocks = []  # list of (font, line_text)

    header = f"Світові новини — {date_str}"
    for line in _wrap_text(tmp_draw, header, title_font, max_text_width):
        blocks.append((title_font, line))
    blocks.append((body_font, ""))  # порожній рядок-відступ

    if not items:
        for line in _wrap_text(tmp_draw, "Сьогодні свіжих новин не знайдено.", body_font, max_text_width):
            blocks.append((body_font, line))
    else:
        for i, item in enumerate(items, start=1):
            title_uk, summary_uk = translate_item(item["title"], item["summary"])
            numbered_title = f"{i}. {title_uk}"

            for line in _wrap_text(tmp_draw, numbered_title, title_font, max_text_width):
                blocks.append((title_font, line))
            if summary_uk:
                for line in _wrap_text(tmp_draw, summary_uk, body_font, max_text_width):
                    blocks.append((body_font, line))
            blocks.append((body_font, ""))  # відступ між новинами
            time.sleep(1.0)

    # Рахуємо загальну висоту
    total_height = MARGIN * 2
    line_heights = []
    for font, line in blocks:
        bbox = tmp_draw.textbbox((0, 0), line or " ", font=font)
        h = (bbox[3] - bbox[1]) + LINE_SPACING
        line_heights.append(h)
        total_height += h

    img = Image.new("RGB", (IMAGE_WIDTH, total_height), "white")
    draw = ImageDraw.Draw(img)

    y = MARGIN
    for (font, line), h in zip(blocks, line_heights):
        if line:
            draw.text((MARGIN, y), line, font=font, fill="black")
        y += h

    img.save(out_path)
    return items  # повертаємо items з (уже перекладеними) для підпису-посилань


def send_photo_to_telegram(image_path, caption=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані.", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    with open(image_path, "rb") as photo_file:
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:1024]
            data["parse_mode"] = "HTML"
        resp = requests.post(url, data=data, files={"photo": photo_file}, timeout=30)

    if resp.status_code != 200:
        print(f"[ERROR] Telegram API повернув {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)
    print("Дайджест-картинку успішно надіслано.")


def send_links_message(items):
    if not items:
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    lines = ["🔗 <b>Джерела:</b>", ""]
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {html.escape(item['source'])} — {item['link']}")
    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=20)

    if resp.status_code != 200:
        print(f"[ERROR] Не вдалося надіслати посилання: {resp.status_code}: {resp.text}", file=sys.stderr)


def main():
    items = fetch_all_items()
    top_items = filter_and_rank(items)

    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    out_path = "/tmp/digest.png"
    render_digest_image(top_items, today, out_path)

    send_photo_to_telegram(out_path)
    send_links_message(top_items)


if __name__ == "__main__":
    main()
