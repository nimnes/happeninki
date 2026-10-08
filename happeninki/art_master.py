"""Art Master's public Joomla calendar, including pagination and detail pages."""
import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from .filters import event_exclusion_reason
from .models import Event, plain_text, safe_url

CITY_NAMES = {"тампере": "Tampere", "нокиа": "Nokia", "ювяскюля": "Jyväskylä",
              "хельсинки": "Helsinki", "куопио": "Kuopio", "турку": "Turku",
              "йоэнсуу": "Joensuu", "эспоо": "Espoo", "лахти": "Lahti"}


def calendar_links(document, base_url):
    articles = re.findall(r"<article\b[^>]*>(.*?)</article>", document, re.S | re.I)
    if not articles:
        raise ValueError("Art Master calendar layout changed")
    events = []
    for article in articles:
        match = re.search(r'href=["\'](/afisha/[^"\']+)["\']', article)
        if not match:
            raise ValueError("Art Master listing has no detail link")
        events.append(urljoin(base_url, match[1]))
    pages = [urljoin(base_url, href.replace("&amp;", "&")) for href in
             re.findall(r'href=["\'](/afisha\?start=\d+)["\']', document)]
    return list(dict.fromkeys(events)), list(dict.fromkeys(pages))


def parse_art_master(document, url, config):
    settings = config["sources"]["art_master"]
    section = re.search(r'<section\b[^>]*class=["\'][^"\']*article-content[^"\']*["\'][^>]*>(.*?)</section>', document, re.S | re.I)
    if not section:
        raise ValueError("Art Master detail page has no event content")
    content = section[1]
    paragraphs = [plain_text(p) for p in re.findall(r'<p\b[^>]*>(.*?)</p>', content, re.S | re.I)]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        raise ValueError("Art Master event is empty")
    description = "\n".join(paragraphs)
    day_month = re.search(r'\b(\d{1,2})\.(\d{1,2})(?:\.(20\d{2}))?\b', paragraphs[0])
    slug = urlsplit(url).path.rsplit("/", 1)[-1]
    numbers = [int(n) for n in re.findall(r'\d+', slug)]
    if not day_month:
        raise ValueError("Art Master event has no date")
    day, month = int(day_month[1]), int(day_month[2])
    if day_month[3]:
        year = int(day_month[3])
    elif len(numbers) >= 3 and numbers[1:3] == [month, day] and 20 <= numbers[0] <= 99:
        year = 2000 + numbers[0]
    elif len(numbers) >= 3 and numbers[:2] == [month, day] and 20 <= numbers[2] <= 99:
        year = 2000 + numbers[2]
    else:
        raise ValueError("Art Master event year cannot be verified")
    # Only the announcement line contains occurrence times; age ranges and dates
    # are never interpreted as times. One listing may announce two performances.
    times = re.findall(r'(?<!\d)(\d{1,2})[.:](\d{2})(?!\d)', re.sub(r'\b\d{1,2}\.\d{1,2}(?:\.20\d{2})?\b', '', paragraphs[0], count=1))
    if not times:
        raise ValueError("Art Master event has no start time")
    dates = []
    for hour, minute in dict.fromkeys(times):
        start = datetime(year, month, day, int(hour), int(minute), tzinfo=ZoneInfo(config["timezone"])).isoformat()
        dates.append({"start": start, "end": start})
    dates.sort(key=lambda item: item["start"])
    city = "Jyväskylä"  # Calendar explicitly gives this as its default venue.
    location_text = " ".join(p for p in paragraphs if not re.match(r'^https?://', p, re.I))
    for spelling, canonical in CITY_NAMES.items():
        if re.search(r'\b' + re.escape(spelling) + r'\b', location_text, re.I):
            city = canonical
            break
    for canonical in settings["municipalities"] + ["Helsinki", "Kuopio", "Turku"]:
        if re.search(r'\b' + re.escape(canonical) + r'\b', location_text, re.I):
            city = canonical
            break
    title_candidates = []
    city_labels = set(CITY_NAMES) | {value.casefold() for value in CITY_NAMES.values()}
    for paragraph in paragraphs[1:]:
        if (paragraph.casefold() in city_labels or re.match(r'^(?:https?://|Билеты)', paragraph, re.I)
                or re.fullmatch(r'[\d\s.+,:–-]+', paragraph)
                or re.match(r'^(?:пн|вт|ср|чт|пт|сб|вс)\.?\s*\d', paragraph, re.I)
                or re.match(r'^\d{1,2}[.:]\d{1,2}', paragraph)):
            continue
        title_candidates.append(paragraph)
    title = title_candidates[0] if title_candidates else paragraphs[0]
    heading = re.search(r'<h1\b[^>]*>(.*?)</h1>', document, re.S | re.I)
    kind = plain_text(heading[1]) if heading else ""
    tags = ["theatre"] if re.search(r'\b(?:спектакль|представление)\b', title + " " + kind, re.I) else ["culture"]
    if re.search(r'для\s+(?:детей|малышей)|\d+\s*[-–]\s*\d+\s*лет|(?:младшая|средняя|старшая)\s+группа', description, re.I):
        tags.append("kids and family")
    links = re.findall(r'href=["\']([^"\']+)["\']', content)
    tickets = next((safe_url(link) for link in links if urlsplit(link).hostname == "fienta.com"), "")
    image = re.search(r'<img\b[^>]*src=["\']([^"\']+)["\']', content, re.I)
    event = Event(source="art_master", source_id=slug, title=title, description=description, url=url,
                  municipality=city, venue="Art-Master" if city == "Jyväskylä" else "",
                  address="Laikuttajantie 2, Jyväskylä" if city == "Jyväskylä" else "",
                  category="culture", start=dates[0]["start"], end=dates[-1]["end"], dates=dates,
                  price="0 €" if "вход свободный" in description.casefold() else "", ticket_url=tickets,
                  image_url=safe_url(urljoin(url, image[1])) if image else "", source_categories=tags,
                  delivery_languages=settings["delivery_languages"], performance_languages=settings["performance_languages"])
    return None if event_exclusion_reason(event, config) else event


class ArtMasterSource:
    name = "art_master"

    def __init__(self, config, http):
        self.config, self.http = config, http

    def fetch(self, start, end):
        base = self.config["sources"][self.name]["base_url"]
        queue, visited, urls = [base + "/afisha"], set(), set()
        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            if len(visited) >= 20:
                raise ValueError("Art Master pagination exceeds expected size")
            visited.add(url)
            document = self.http.request(url, service="Art Master", raw=True).decode("utf-8")
            links, pages = calendar_links(document, base)
            urls.update(links)
            queue.extend(page for page in pages if page not in visited)
        events = []
        for url in sorted(urls):
            document = self.http.request(url, service="Art Master", raw=True).decode("utf-8")
            event = parse_art_master(document, url, self.config)
            if event and event.overlaps(start, end):
                events.append(event)
        return events
