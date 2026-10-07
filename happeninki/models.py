import calendar
import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "li", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "li", "div"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    parser = TextParser()
    parser.feed(str(value or ""))
    return " ".join(html.unescape("".join(parser.parts)).split())


def safe_url(value):
    parts = urlsplit(value or "")
    return value if parts.scheme in {"http", "https"} and parts.netloc and not parts.username else ""


def next_month(day):
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def parse_datetime(value, timezone):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone) if dt.tzinfo is None else dt.astimezone(timezone)


def normalized(value):
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


@dataclass
class Event:
    source: str
    source_id: str
    title: str
    description: str
    url: str
    municipality: str
    venue: str
    address: str
    category: str
    start: str
    end: str
    dates: list
    date_only: bool = False
    price: str = ""
    cancelled: bool = False
    ticket_url: str = ""
    source_categories: list = field(default_factory=list)

    @property
    def source_key(self):
        return f"{self.source}:{self.source_id}"

    @property
    def canonical_key(self):
        # Conservative exact matching. Different dates/venues stay separate.
        identity = [normalized(self.title), normalized(self.municipality),
                    normalized(self.address or self.venue), self.start, self.end]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()

    @property
    def fingerprint(self):
        data = asdict(self)
        for key in ("source", "source_id", "url", "source_categories"):
            data.pop(key)
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @property
    def text_fingerprint(self):
        return hashlib.sha256((self.title + "\n" + self.description).encode()).hexdigest()

    def active_on(self, day):
        return date.fromisoformat(self.end[:10]) >= day

    def overlaps(self, start, end):
        if self.dates:
            return any(date.fromisoformat(d["end"][:10]) >= start
                       and date.fromisoformat(d["start"][:10]) <= end for d in self.dates)
        return date.fromisoformat(self.end[:10]) >= start and date.fromisoformat(self.start[:10]) <= end
