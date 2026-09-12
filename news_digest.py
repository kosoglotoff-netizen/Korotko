#!/usr/bin/env python3
"""
Щоденний дайджест світових новин у Telegram.

Бере кілька надійних RSS-стрічок, витягує лід (короткий зміст) кожної статті,
відфільтровує спортивні новини, перекладає українською (безкоштовно, без API-ключа)
і надсилає дайджест у Telegram-чат/канал через Bot API.

Змінні середовища (задаються як GitHub Secrets):
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

# Скільки новин публікувати за раз
MAX_ITEMS = 8

# Не показувати новини старіші за це число годин (уникнути дублів day-to-day)
MAX_AGE_HOURS = 30

# Максимальна довжина ліда (символів) до перекладу
LEAD_MAX_CHARS = 400

# Ключові слова для відсіювання спортивних новин
SPORT_KEYWORDS = [
    "football", "soccer", "nba", "nfl", "nhl", "mlb", "tennis", "golf",
    "cricket", "rugby", "olympic", "olympics", "athlete", "match", "tournament",
    "championship", "world cup", "premier league", "la liga", "bundesliga",
    "serie a", "champions league", "wimbledon", "grand slam", "formula 1",
    " f1 ", "boxing", "ufc", "mma", "medal", "coach", "stadium", "playoffs",
    "goalkeeper", "midfielder", "striker", "referee", "world series",
    "super bowl", "grand prix", "marathon", "cyclist", "cycling", "sport",
]


def is_sports(title, summary, categories):
    text = f"{title} {summary}".lower()
    for kw in SPORT_KEYWORDS:
        if kw in text:
            return True
    for cat in categories:
        if "sport" in cat.lower():
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
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
            else:
                pub_dt = datetime.now(timezone.utc)

            categories = [t.get("term", "") for t in entry.get("tags", [])] if entry.get("tags") else []
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = clean_html(summary_raw)[:LEAD_MAX_CHARS]
            title = entry.get("title", "").strip()

            if is_sports(title, summary, categories):
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

    # Прибираємо явні дублі заголовків між джерелами
    seen_titles = set()
    unique = []
    for item in fresh:
        key = item["title"].lower()[:60]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(item)

    return unique[:MAX_ITEMS]


# Ознаки того, що замість перекладу повернулась сторінка помилки перекладача
_ERROR_MARKERS = ("error 500", "that\u2019s an error", "that's an error", "please try again later")


def _looks_like_error(text):
    if not text:
        return True
    low = text.lower()
    return any(marker in low for marker in _ERROR_MARKERS)


def translate_text(text, retries=3, base_delay=2.0):
    """Перекладає текст українською. Пробує Google Translate (безкоштовний доступ)
    з повторними спробами при тимчасовому блокуванні, потім MyMemory як запасний варіант."""
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

    # Запасний перекладач, якщо Google тимчасово заблокував запити
    try:
        chunk = text[:490]  # MyMemory обмежує довжину запиту
        result = MyMemoryTranslator(source="en-GB", target="uk-UA").translate(chunk)
        if result and not _looks_like_error(result):
            return result
    except Exception as e:
        print(f"[WARN] MyMemoryTranslator також не вдався: {e}", file=sys.stderr)

    print("[WARN] Переклад не вдався, лишаю оригінал англійською.", file=sys.stderr)
    return text


def translate_item(title, summary):
    """Перекладає заголовок і лід одним запитом (щоб зменшити кількість звернень
    до безкоштовного перекладача і не наштовхнутись на обмеження частоти)."""
    if not summary:
        return translate_text(title), ""

    combined = f"{title}\n{summary}"
    translated = translate_text(combined)

    if "\n" in translated:
        parts = translated.split("\n", 1)
        return parts[0].strip(), parts[1].strip()

    # Якщо переклад "з'їв" перенос рядка — перекладаємо окремо
    return translate_text(title), translate_text(summary)


def build_message(items):
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    lines = [f"🌍 <b>Світові новини — {today}</b>", ""]

    if not items:
        lines.append("Сьогодні свіжих новин зі стрічок не знайдено.")
    else:
        for i, item in enumerate(items, start=1):
            title_uk_raw, summary_uk_raw = translate_item(item["title"], item["summary"])
            title_uk = html.escape(title_uk_raw)
            summary_uk = html.escape(summary_uk_raw)

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

    # Telegram обмежує повідомлення 4096 символами — ріжемо на частини за потреби
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
