import logging
import re
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from .models import Event, parse_datetime, plain_text, safe_url
from .filters import exclusion_reason, is_finnish_learning
from .art_master import ArtMasterSource

LOG = logging.getLogger(__name__)
FREE_CATEGORY = "6170601b7a45476ff366cb18"


def category_for(page, config):
    if ("language_learning" in config["categories"] and config.get("filters", {}).get("allow_finnish_learning")
            and is_finnish_learning(plain_text(page.get("name")),
                                    plain_text(page.get("descriptionLong") or page.get("descriptionShort")))):
        return "language_learning"
    categories = set(page.get("globalContentCategories", []))
    # Specific categories win over general cultural tags.
    for name in ("festivals", "exhibitions", "music", "food", "culture"):
        if name in config["categories"] and categories.intersection(config["category_mapping"][name]):
            return name
    return None


def price_for(page):
    if FREE_CATEGORY in page.get("categories", []):
        return "0 €"
    price = page.get("price") or {}
    low, high = price.get("min"), price.get("max")
    if low is None:
        return ""
    return f"{low:g} €" if high is None or high == low else f"{low:g}–{high:g} €"


def parse_tampere(page, municipality, config):
    if page.get("pageType") != "event" or page.get("privacy", "public") != "public":
        return None
    title = plain_text(page.get("name"))
    description = plain_text(page.get("descriptionLong") or page.get("descriptionShort"))
    source_categories = page.get("globalContentCategories", [])
    if not title or exclusion_reason(title, description, source_categories, config):
        return None
    category = category_for(page, config)
    if not category:
        return None
    timezone = ZoneInfo(config["timezone"])
    details = page.get("event") or {}
    date_only = details.get("datesType") == "schedule"
    dates = []
    if date_only:
        schedule = page.get("schedule") or {}
        start = schedule.get("start") or page.get("defaultStartDate")
        end = schedule.get("end") or page.get("defaultEndDate") or start
    else:
        for item in details.get("dates", []):
            if not item.get("start"):
                continue
            beginning = parse_datetime(item["start"], timezone)
            finish = parse_datetime(item.get("end") or item["start"], timezone)
            if finish < beginning:
                raise ValueError("Event occurrence ends before it starts")
            dates.append({"start": beginning.isoformat(), "end": finish.isoformat()})
        dates.sort(key=lambda d: d["start"])
        start = dates[0]["start"] if dates else details.get("start") or page.get("defaultStartDate")
        end = max(d["end"] for d in dates) if dates else details.get("end") or page.get("defaultEndDate") or start
    if not start:
        raise ValueError("Matching event has no start date")
    start = parse_datetime(start, timezone)
    end = parse_datetime(end, timezone)
    if end < start:
        raise ValueError("Event ends before it starts")
    locations = page.get("locations") or []
    address = plain_text(locations[0].get("address")) if locations and not page.get("hideAddress") else ""
    for city in config["municipalities"]:
        if re.search(r"\b" + re.escape(city) + r"\b", address, re.IGNORECASE):
            municipality = city
            break
    venue = address.split(",")[0] if address else ""
    source_id = page.get("_id")
    if not source_id:
        raise ValueError("Matching event has no ID")
    return Event(
        source="tampere", source_id=source_id, title=title,
        description=description,
        url=f"{config['sources']['tampere']['base_url']}/fi-FI/page/{source_id}",
        municipality=municipality, venue=venue, address=address, category=category,
        start=start.isoformat(), end=end.isoformat(), dates=dates, date_only=date_only,
        price=price_for(page), cancelled=bool(details.get("isCancelled")),
        ticket_url=safe_url(details.get("urlPurchaseTicket", "")),
        source_categories=source_categories,
        image_url=(f"https://cdn.townbase.com/images/{page['imageDesktop']}"
                   if re.fullmatch(r"[0-9a-f]{64}", str(page.get("imageDesktop", ""))) else ""),
    )


class TampereSource:
    name = "tampere"

    def __init__(self, config, http):
        self.config, self.http = config, http

    def fetch(self, start, end):
        from urllib.parse import urlencode
        settings = self.config["sources"]["tampere"]
        result = {}
        for municipality in self.config["municipalities"]:
            area = settings["areas"].get(municipality)
            if not area:
                raise ValueError(f"No Tampere calendar area ID configured for {municipality}")
            cursor = start
            while cursor <= end:
                finish = min(cursor + timedelta(days=settings["window_days"] - 1), end)
                query = urlencode({"lang": "fi", "country": "FI", "mode": "event",
                                   "area_id": area, "start": cursor.isoformat(),
                                   "end": finish.isoformat(), "sort": "startDate"})
                data = self.http.request(f"{settings['base_url']}/api/collection/{settings['collection_id']}/content?{query}", service="Tampere calendar")
                if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
                    raise ValueError("Tampere calendar response has no pages list")
                # The verified frontend endpoint returns its entire date-filtered set.
                # Refuse unexpected pagination instead of silently losing coverage.
                if data.get("hasMore") or data.get("next"):
                    raise ValueError("Tampere calendar pagination changed; connector needs updating")
                for page in data["pages"]:
                    event = parse_tampere(page, municipality, self.config)
                    if event and event.overlaps(start, end):
                        # Date-filtered API occurrences can differ between windows.
                        previous = result.get(event.source_key)
                        if previous and not event.date_only:
                            merged = {d["start"]: d for d in previous.dates + event.dates}
                            event.dates = sorted(merged.values(), key=lambda d: d["start"])
                            event.start = event.dates[0]["start"]
                            event.end = max(d["end"] for d in event.dates)
                        result[event.source_key] = event
                cursor = finish + timedelta(days=1)
                time.sleep(0.1)
        return list(result.values())


def parse_syo(campaign, config):
    if campaign is None:
        return []  # Verified response when no current/upcoming campaign is published.
    if not isinstance(campaign, dict) or not all(campaign.get(k) for k in ("id", "startDate", "endDate")):
        raise ValueError("SYÖ campaign schema changed")
    if not isinstance(campaign.get("cities"), list):
        raise ValueError("SYÖ campaign has no cities list")
    timezone = ZoneInfo(config["timezone"])
    start = parse_datetime(campaign["startDate"], timezone).date()
    end = parse_datetime(campaign["endDate"], timezone).date()
    events = []
    for city in campaign["cities"]:
        municipality = city.get("name", "")
        if municipality not in config["municipalities"]:
            continue
        # Announce the campaign once per city, not every restaurant offer.
        events.append(Event(
            source="syo", source_id=f"{campaign['id']}:{municipality}",
            title=f"SYÖ!-viikot – {municipality}",
            description="SYÖ!-viikot ravintolakampanja. Osallistuvat ravintolat, annokset ja ajantasaiset hinnat löytyvät kampanjan verkkosivulta.",
            url=config["sources"]["syo"]["base_url"], municipality=municipality,
            venue="", address="", category="food", start=start.isoformat(), end=end.isoformat(),
            dates=[], date_only=True,
        ))
    return events


class SyoSource:
    name = "syo"

    def __init__(self, config, http):
        self.config, self.http = config, http

    def fetch(self, start, end):
        if "food" not in self.config["categories"]:
            return []
        settings = self.config["sources"]["syo"]
        campaign = self.http.request(f"{settings['base_url']}/apip/campaign/currentNext/{settings['campaign_type_id']}", service="SYÖ!-viikot")
        if campaign and "cities" not in campaign and campaign.get("id"):
            campaign = self.http.request(f"{settings['base_url']}/apip/campaign/{campaign['id']}", service="SYÖ!-viikot")
        return [event for event in parse_syo(campaign, self.config) if event.overlaps(start, end)]


def collect(config, http, start, end):
    events, failures = [], []
    for source_class in (TampereSource, SyoSource, ArtMasterSource):
        if not config["sources"].get(source_class.name, {}).get("enabled", False):
            continue
        try:
            batch = source_class(config, http).fetch(start, end)
            LOG.info("%s: %d matching listings", source_class.name, len(batch))
            events.extend(batch)
        except Exception as exc:
            LOG.error("%s failed: %s", source_class.name, exc)
            failures.append(source_class.name)
    if not any(config["sources"].get(name, {}).get("enabled", False) for name in ("tampere", "syo", "art_master")):
        raise ValueError("Enable at least one event source")
    return sorted(events, key=lambda e: (e.start, e.title)), failures
