import hashlib
import html
import re
import time
from datetime import datetime
from urllib.parse import urlencode

from .http import RemoteError
from .models import safe_url

LABELS = {
    "en": {"music": "🎵 Music", "exhibitions": "🖼 Exhibitions", "festivals": "🎉 Festivals",
           "food": "🍴 Food", "culture": "🎭 Culture", "language_learning": "🇫🇮 Finnish learning", "source": "Event details", "tickets": "Tickets",
           "cancelled": "❌ Cancelled", "more": "More dates and opening hours at the source"},
    "ru": {"music": "🎵 Музыка", "exhibitions": "🖼 Выставки", "festivals": "🎉 Фестивали",
           "food": "🍴 Еда", "culture": "🎭 Культура", "language_learning": "🇫🇮 Финский язык", "source": "Подробнее о событии", "tickets": "Билеты",
           "cancelled": "❌ Отменено", "more": "Другие даты и часы работы — по ссылке"},
}


def channel_hash(channel):
    return hashlib.sha256(channel.encode()).hexdigest()


def date_label(value, date_only=False):
    dt = datetime.fromisoformat(value)
    return dt.strftime("%d.%m.%Y" if date_only else "%d.%m.%Y %H:%M")


def location_label(event):
    parts, seen = [], set()
    for value in (event.address or event.venue, event.municipality):
        for part in value.split(","):
            part = re.sub(r"^(?:FI-)?\d{5}(?:\s+|$)", "", part.strip(), flags=re.I).strip()
            if part and part.casefold() not in seen:
                parts.append(part)
                seen.add(part.casefold())
    return ", ".join(parts)


def build_message(event, translation, language, today, max_length=4096):
    labels = LABELS[language]
    lines = [labels[event.category]]
    if event.cancelled:
        lines.append(labels["cancelled"])
    lines.extend(["", "<b>" + html.escape(translation["title"]) + "</b>", "", html.escape(translation["summary"]), ""])
    if event.dates:
        dates = [d for d in event.dates if datetime.fromisoformat(d["end"]).date() >= today]
        for item in dates[:5]:
            start, end = date_label(item["start"]), date_label(item["end"])
            lines.append("🗓 " + start + (" – " + end if end != start else ""))
        if len(dates) > 5:
            lines.append(labels["more"])
    else:
        start, end = date_label(event.start, event.date_only), date_label(event.end, event.date_only)
        lines.append("🗓 " + start + (" – " + end if end != start else ""))
        if event.date_only:
            lines.append(labels["more"])
    location = location_label(event)
    if location:
        maps_url = "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": location})
        lines.append(f'📍 <a href="{html.escape(maps_url, quote=True)}">{html.escape(location)}</a>')
    if event.price and not re.fullmatch(r"\s*0(?:[.,]0+)?\s*(?:€|EUR|euros?)\s*", event.price, re.I):
        lines.append("💶 " + html.escape(event.price))
    lines.append("")
    for url, label in ((event.url, labels["source"]), (event.ticket_url, labels["tickets"])):
        if safe_url(url):
            lines.append(f'<a href="{html.escape(url, quote=True)}">{label}</a>')
    message = "\n".join(lines)
    if len(message.encode("utf-16-le")) // 2 > max_length:
        summary = translation["summary"]
        if max_length < 4096 and len(summary) > 1:
            shorter = dict(translation, summary=summary[:max(0, len(summary) - 80)].rstrip() + "…")
            if shorter["summary"] != summary:
                return build_message(event, shorter, language, today, max_length)
        raise ValueError("Formatted event exceeds Telegram's message length")
    return message


class Telegram:
    def __init__(self, http, token, channels):
        channels = {language: channel.strip() for language, channel in channels.items()
                    if language in {"ru", "en"} and channel and channel.strip()}
        if not token:
            raise ValueError("Set TELEGRAM_BOT_TOKEN")
        if not channels:
            raise ValueError("Set at least one of TELEGRAM_CHANNEL_RU or TELEGRAM_CHANNEL_EN")
        if len(channels) == 2 and channels["ru"] == channels["en"]:
            raise ValueError("Russian and English must use different Telegram channels")
        self.http, self.token, self.channels = http, token, channels

    def publish(self, language, message, message_id=None, image_url="", message_kind="text"):
        self.last_message_kind = "photo" if image_url or message_kind == "photo" else "text"
        method = "editMessageText" if message_id is not None else "sendMessage"
        payload = {"chat_id": self.channels[language], "text": message, "parse_mode": "HTML",
                   "link_preview_options": {"is_disabled": True}}
        if message_id is not None:
            payload["message_id"] = message_id
        if self.last_message_kind == "photo":
            payload.pop("text")
            payload.pop("link_preview_options")
            if message_id is None:
                method = "sendPhoto"
                payload.update(photo=image_url, caption=message)
            elif image_url:
                method = "editMessageMedia"
                payload.pop("parse_mode")
                payload["media"] = {"type": "photo", "media": image_url, "caption": message, "parse_mode": "HTML"}
            else:
                method = "editMessageCaption"
                payload["caption"] = message
        try:
            # Do not blindly retry ambiguous sends: the request may have succeeded.
            response = self.http.request(f"https://api.telegram.org/bot{self.token}/{method}",
                method="POST", body=payload, service="Telegram", retry=False)
        except RemoteError as exc:
            image_errors = ("failed to get http url content", "wrong file identifier/http url specified",
                            "wrong type of the web page content", "image_process_failed", "photo_invalid_dimensions")
            if image_url and message_id is None and exc.status == 400 and any(
                    reason in exc.description.casefold() for reason in image_errors):
                # A definite rejection is safe to replace with one text post.
                return self.publish(language, message)
            if message_id is not None and exc.status == 400 and exc.description.startswith("Bad Request: message is not modified"):
                return message_id
            if exc.status != 429:
                raise
            raise RuntimeError("Telegram is throttling publication; remaining events stay queued") from None
        if not response.get("ok") or not isinstance(response.get("result"), dict):
            raise RuntimeError("Telegram did not confirm publication")
        time.sleep(1.1)
        return response["result"]["message_id"]
