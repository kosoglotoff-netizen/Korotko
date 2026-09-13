#!/usr/bin/env python3
"""
Щоденний дайджест світових новин у Telegram — текстом, транслітерованим
у глаголицю (Unicode-блок U+2C00–U+2C5F).

Бере кілька надійних RSS-стрічок, витягує лід кожної статті, відфільтровує
спорт/шоубізнес/кримінал/локальні трагедії, перекладає українською
(безкоштовно, без API-ключа) і транслітерує результат у глаголичні
Unicode-символи перед надсиланням у Telegram.

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

# --- Джерела новин: великі, надійні агенції зі світовим охопленням ---
FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
]

MAX_ITEMS = 8
MAX_AGE_HOURS = 30
LEAD_MAX_CHARS = 400

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


# --- Транслітерація українського тексту в глаголицю (Unicode-блок U+2C00–U+2C5F) ---
# Кожній сучасній українській літері відповідає окремий, унікальний глаголичний
# символ (без повторного використання того самого знака для різних літер).
_GLAGOLITIC_BASE = {
    "А": 0x2C00,  # Азъ
    "Б": 0x2C01,  # Букы
    "В": 0x2C02,  # Вѣдѣ
    "Г": 0x2C03,  # Глаголи
    "Ґ": 0x2C0C,  # Джерв
    "Д": 0x2C04,  # Добро
    "Е": 0x2C05,  # Есть
    "Є": 0x2C27,  # Йотований малий юс
    "Ж": 0x2C06,  # Живѣте
    "З": 0x2C08,  # Земля
    "И": 0x2C0B,  # І (проста форма)
    "І": 0x2C09,  # Иже
    "Ї": 0x2C0A,  # Початкове иже
    "Й": 0x2C24,  # Малий юс
    "К": 0x2C0D,  # Како
    "Л": 0x2C0E,  # Людіє
    "М": 0x2C0F,  # Мыслите
    "Н": 0x2C10,  # Нашь
    "О": 0x2C11,  # Онъ
    "П": 0x2C12,  # Покои
    "Р": 0x2C13,  # Рьци
    "С": 0x2C14,  # Слово
    "Т": 0x2C15,  # Тврьдо
    "У": 0x2C16,  # Укъ
    "Ф": 0x2C17,  # Ферть
    "Х": 0x2C18,  # Херъ
    "Ц": 0x2C1C,  # Ци
    "Ч": 0x2C1D,  # Червь
    "Ш": 0x2C1E,  # Ша
    "Щ": 0x2C1B,  # Шта
    "Ь": 0x2C1F,  # Єрь (твердий/м'який знак)
    "Ю": 0x2C23,  # Ю
    "Я": 0x2C21,  # Ять
}


def _glagolitic_char(ch):
    upper = ch.upper()
    is_lower = ch.islower()

    if upper in _GLAGOLITIC_BASE:
        codepoint = _GLAGOLITIC_BASE[upper]
        if is_lower:
            codepoint += 0x30
        return chr(codepoint)

    return ch  # цифри, пунктуація, пробіли, латиниця — без змін


def to_glagolitic(text):
    if not text:
        return text
    return "".join(_glagolitic_char(ch) for ch in text)


def build_message(items):
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    header = to_glagolitic(f"🌍 Світові новини — {today}")
    lines = [f"<b>{header}</b>", ""]

    if not items:
        lines.append(to_glagolitic("Сьогодні свіжих новин зі стрічок не знайдено."))
    else:
        for i, item in enumerate(items, start=1):
            title_uk_raw, summary_uk_raw = translate_item(item["title"], item["summary"])
            title_uk = html.escape(to_glagolitic(title_uk_raw))
            summary_uk = html.escape(to_glagolitic(summary_uk_raw))

            lines.append(f"{i}. <b>{title_uk}</b>")
            if summary_uk:
                lines.append(summary_uk)
            lines.append(f"📰 {item['source']} — {item['link']}")
            lines.append("")
            time.sleep(1.0)

    return "\n".join(lines)


def send_to_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані.", file=sys.stderr)
        sys.exit(1)

    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in chunks:
        resp = requests.post(url, data={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }, timeout=20)

        if resp.status_code != 200:
            print(f"[ERROR] Telegram API повернув {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)

    print("Дайджест успішно надіслано.")


def main():
    items = fetch_all_items()
    top_items = filter_and_rank(items)
    message = build_message(top_items)
    send_to_telegram(message)


if __name__ == "__main__":
    main()
