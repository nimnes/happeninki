import tempfile
import unittest
from datetime import date
from pathlib import Path

from happeninki.art_master import ArtMasterSource, calendar_links, parse_art_master
from happeninki.config import load_config
from happeninki.filters import event_exclusion_reason
from happeninki.models import next_month
from happeninki.store import Store
from happeninki.sources import collect


class ArtMasterTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.base = self.config["sources"]["art_master"]["base_url"]

    def fixture(self, name):
        return (Path(__file__).parent / "fixtures" / name).read_text()

    def test_helsinki_adult_play_date_and_title(self):
        event = parse_art_master(self.fixture("art-master-helsinki.html"), self.base + "/afisha/afisha-26-12-05", self.config)
        self.assertEqual(event.title, "Я АНФАС, или ДОРОГОЙ ДНЕВНИК")
        self.assertEqual(event.start, "2026-12-05T20:00:00+02:00")
        self.assertEqual(event.municipality, "Helsinki")
        self.assertEqual(event.address, "")  # Do not invent a touring venue address.
        self.assertEqual(event.source_categories, ["theatre"])
        self.assertEqual(event.delivery_languages, ["ru"])
        self.assertTrue(event.ticket_url.startswith("https://fienta.com/"))
        self.assertIsNone(event_exclusion_reason(event, self.config))
        self.assertNotIn("Helsinki", self.config["municipalities"])

    def test_children_filtered_and_multiple_performances_parsed(self):
        for name, slug in (("art-master-children.html", "afisha-26-12-06"),
                           ("art-master-multiple.html", "afisha-12-20-26-1")):
            self.assertIsNone(parse_art_master(self.fixture(name), self.base + "/afisha/" + slug, self.config))
        self.config["filters"]["exclude_children"] = False
        event = parse_art_master(self.fixture("art-master-multiple.html"), self.base + "/afisha/afisha-12-20-26-1", self.config)
        self.assertEqual(len(event.dates), 2)
        self.assertEqual(event.start, "2026-12-20T13:00:00+02:00")
        self.assertEqual(event.end, "2026-12-20T15:00:00+02:00")
        self.assertEqual(event.municipality, "Jyväskylä")

    def test_unknown_year_rejected_and_outside_city_skipped(self):
        document = self.fixture("art-master-helsinki.html")
        with self.assertRaisesRegex(ValueError, "year"):
            parse_art_master(document, self.base + "/afisha/new-play", self.config)
        self.assertIsNone(parse_art_master(document.replace("ХЕЛЬСИНКИ", "КУОПИО"),
                          self.base + "/afisha/afisha-26-12-05", self.config))

    def test_only_russian_channel_queued_and_history_reused(self):
        event = parse_art_master(self.fixture("art-master-helsinki.html"), self.base + "/afisha/afisha-26-12-05", self.config)
        today = date(2026, 11, 20)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "events.db")
            store.ingest([event], today, next_month(today))
            pending = store.pending(today, ["ru", "en"], {"ru": "ru", "en": "en"})
            self.assertEqual(pending[0][2], ["ru"])
            store.mark_published(pending[0][0], "ru", "ru", 42, event.fingerprint)
            store.ingest([event], today, next_month(today))
            self.assertEqual(store.pending(today, ["ru", "en"], {"ru": "ru", "en": "en"}), [])
            store.close()

    def test_pagination_fetches_all_pages_and_details_once(self):
        document = self.fixture("art-master-helsinki.html")
        event_url = self.base + "/afisha/afisha-26-12-05"
        first = '<article><a href="/afisha/afisha-26-12-05">Play</a></article>'
        first += '<a href="/afisha?start=10">2</a>'
        calls = []
        class Http:
            def request(_, url, **kwargs):
                calls.append(url)
                return (document if url == event_url else first).encode()
        events = ArtMasterSource(self.config, Http()).fetch(date(2026, 10, 8), date(2027, 4, 6))
        self.assertEqual(len(events), 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls.count(event_url), 1)
        with self.assertRaises(ValueError):
            calendar_links('<html>Unexpected page</html>', self.base)

    def test_changed_calendar_is_reported_as_source_failure(self):
        self.config["sources"]["tampere"]["enabled"] = False
        self.config["sources"]["syo"]["enabled"] = False
        class Http:
            def request(self, *args, **kwargs):
                return b'<html>Unexpected page</html>'
        events, failures = collect(self.config, Http(), date(2026, 10, 8), date(2027, 4, 6))
        self.assertEqual(events, [])
        self.assertEqual(failures, ["art_master"])


if __name__ == "__main__":
    unittest.main()
