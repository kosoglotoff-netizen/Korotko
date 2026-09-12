#!/usr/bin/env python3
"""
Щоденний дайджест світових новин у Telegram.

Бере кілька надійних RSS-стрічок, вибирає найсвіжіші новини та
надсилає короткий дайджест у Telegram-чат/канал через Bot API.

Змінні середовища (задаються як GitHub Secrets або локально):
    TELEGRAM_BOT_TOKEN  — токен бота від @BotFather
    TELEGRAM_CHAT_ID    — ID чату/каналу, куди слати повідомлення
"""

import os
import sys
import html
from datetime import datetime, timezone, timedelta

import feedparser
import requests

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

            items.append({
                "source": source_name,
                "title": entry.get("title", "").strip(),
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


def build_message(items):
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    lines = [f"🌍 <b>Світові новини — {today}</b>", ""]

    if not items:
        lines.append("Сьогодні свіжих новин зі стрічок не знайдено.")
    else:
        for i, item in enumerate(items, start=1):
            title = html.escape(item["title"])
            lines.append(f"{i}. <b>{title}</b>")
            lines.append(f"   📰 {item['source']} — {item['link']}")
            lines.append("")

    return "\n".join(lines)


def send_to_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані.", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": chat_id,
        "text": text,
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
