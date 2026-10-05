import copy
import hashlib
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from happeninki.__main__ import publish_pending
from happeninki.config import load_config
from happeninki.http import RemoteError
from happeninki.models import Event, next_month
from happeninki.releases import ReleaseState
from happeninki.sources import TampereSource, parse_syo, parse_tampere
from happeninki.store import Store, validate_database
from happeninki.telegram import Telegram, build_message, channel_hash
from happeninki.translator import TranslationUnavailable, Translator


TODAY = date(2026, 10, 5)
HASHES = {language: channel_hash(language) for language in ("ru", "en")}


def event(**kwargs):
    defaults = dict(source="test", source_id="1", title="Test concert", description="A concert",
                    url="https://example.org/event", municipality="Tampere", venue="Venue",
                    address="Venue, Street 1", category="music", start="2026-10-20T19:00:00+03:00",
                    end="2026-10-20T21:00:00+03:00", dates=[])
    defaults.update(kwargs)
    return Event(**defaults)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def fixture(self, name):
        return json.loads((Path(__file__).parent / "fixtures" / name).read_text())

    def test_verified_individual_dates_schema(self):
        page = self.fixture("tampere-individual-dates.json")
        parsed = parse_tampere(page, "Tampere", self.config)
        self.assertTrue(parsed.dates)
        self.assertIn("+03:00", parsed.start)
        self.assertNotIn("<p>", parsed.description)
        self.assertEqual(parsed.price, "0 €")

    def test_verified_schedule_schema_does_not_invent_opening_hours(self):
        parsed = parse_tampere(self.fixture("tampere-schedule.json"), "Tampere", self.config)
        self.assertTrue(parsed.date_only)
        self.assertFalse(parsed.dates)
        self.assertEqual(parsed.start[:10], "2026-10-07")

    def test_excluded_class_and_unknown_categories(self):
        page = self.fixture("tampere-individual-dates.json")
        page["name"] = "Lasten tanssikurssit"
        self.assertIsNone(parse_tampere(page, "Tampere", self.config))
        page["name"] = "Something"
        page["globalContentCategories"] = ["sports and fitness"]
        self.assertIsNone(parse_tampere(page, "Tampere", self.config))

    def test_missing_date_rejects_matching_event(self):
        page = self.fixture("tampere-individual-dates.json")
        page["event"] = {}
        page.pop("defaultStartDate", None)
        self.assertRaises(ValueError, parse_tampere, page, "Tampere", self.config)

    def test_price_absent_is_not_free(self):
        page = self.fixture("tampere-individual-dates.json")
        page["categories"] = []
        page.pop("price", None)
        self.assertEqual(parse_tampere(page, "Tampere", self.config).price, "")

    def test_syo_null_is_normal_and_one_event_per_city(self):
        self.assertEqual(parse_syo(None, self.config), [])
        # Synthetic positive schema: no future campaign was available at inspection.
        parsed = parse_syo({"id": 12, "startDate": "2026-10-10", "endDate": "2026-10-23",
                            "cities": [{"name": "Tampere"}, {"name": "Helsinki"}]}, self.config)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].municipality, "Tampere")
        self.assertEqual(parsed[0].price, "")
        self.assertTrue(parsed[0].date_only)

    @patch("happeninki.sources.time.sleep")
    def test_date_windows_merge_occurrences(self, _sleep):
        page = self.fixture("tampere-individual-dates.json")
        config = copy.deepcopy(self.config)
        config["municipalities"] = ["Tampere"]
        config["sources"]["tampere"]["window_days"] = 1
        class Http:
            calls = 0
            def request(self, url, **kwargs):
                self.calls += 1
                response = copy.deepcopy(page)
                response["event"]["dates"] = [{"start": f"2026-10-0{self.calls + 4}T10:00:00Z",
                                               "end": f"2026-10-0{self.calls + 4}T11:00:00Z"}]
                return {"pages": [response]}
        parsed = TampereSource(config, Http()).fetch(TODAY, date(2026, 10, 6))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(parsed[0].dates), 2)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "events.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def ingest(self, events, today=TODAY):
        self.store.ingest(events, today, next_month(today))

    def test_first_month_and_ongoing_exhibition(self):
        self.ingest([event(), event(source_id="2", start="2026-12-01", end="2026-12-02"),
                     event(source_id="3", start="2026-09-01", end="2026-11-01", date_only=True)])
        pending = self.store.pending(TODAY, ["ru", "en"], HASHES)
        self.assertEqual(len(pending), 2)
        self.ingest([event(source_id="4", start="2026-12-03", end="2026-12-04")])
        self.assertEqual(len(self.store.pending(TODAY, ["ru", "en"], HASHES)), 3)

    def test_language_success_survives_restart_and_change_updates(self):
        item = event()
        self.ingest([item])
        key = self.store.pending(TODAY, ["ru", "en"], HASHES)[0][0]
        self.store.mark_published(key, "ru", HASHES["ru"], 123, item.fingerprint)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.pending(TODAY, ["ru", "en"], HASHES)[0][2], ["en"])
        self.ingest([replace(item, price="20 €")])
        self.assertEqual(self.store.pending(TODAY, ["ru", "en"], HASHES)[0][2], ["ru", "en"])
        self.assertEqual(self.store.publication(key, "ru", HASHES["ru"])["message_id"], 123)

    def test_duplicate_sources_share_one_event(self):
        item = event()
        self.ingest([item, replace(item, source="another", source_id="42")])
        self.assertEqual(len(self.store.pending(TODAY, ["ru", "en"], HASHES)), 1)

    def test_rolling_window_does_not_edit_post(self):
        first = {"start": "2026-10-05T10:00:00+03:00", "end": "2026-10-05T11:00:00+03:00"}
        second = {"start": "2026-10-20T10:00:00+03:00", "end": "2026-10-20T11:00:00+03:00"}
        item = event(start=first["start"], end=second["end"], dates=[first, second])
        self.ingest([item])
        key = self.store.pending(TODAY, ["ru"], HASHES)[0][0]
        self.store.mark_published(key, "ru", HASHES["ru"], 123, item.fingerprint)
        self.ingest([replace(item, start=second["start"], dates=[second])], date(2026, 10, 6))
        self.assertEqual(self.store.pending(date(2026, 10, 6), ["ru"], HASHES), [])

    def test_cache_reused_for_price_change_but_not_description(self):
        item = event()
        self.store.cache_translation(item, "ru", {"title": "Title", "summary": "Summary"})
        self.assertIsNotNone(self.store.translation(replace(item, price="20 €"), "ru"))
        self.assertIsNone(self.store.translation(replace(item, description="Changed"), "ru"))

    def test_cancelled_new_event_is_not_announced(self):
        self.ingest([event(cancelled=True)])
        self.assertEqual(self.store.pending(TODAY, ["ru", "en"], HASHES), [])

    def test_finished_event_today_is_not_announced(self):
        self.ingest([event(start="2026-10-05T10:00:00+03:00", end="2026-10-05T11:00:00+03:00")])
        self.assertEqual(self.store.pending(TODAY, ["ru", "en"], HASHES,
                         now=datetime.fromisoformat("2026-10-05T12:00:00+03:00")), [])

    def test_snapshot_validation(self):
        self.ingest([event()])
        snapshot = Path(self.directory.name) / "snapshot.db"
        self.store.snapshot(snapshot)
        validate_database(snapshot)
        snapshot.write_bytes(b"bad data")
        with self.assertRaises(Exception):
            validate_database(snapshot)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "events.db")
        self.config = load_config()
        class FakeTelegram:
            channels = {"ru": "ru", "en": "en"}
            calls = []
            def publish(self, language, message, message_id=None):
                self.calls.append((language, message_id))
                if language == "en":
                    raise RuntimeError("Temporary failure")
                return 321
        self.telegram = FakeTelegram()
        class FakeTranslator:
            def translate(self, event, language):
                return {"title": "Translated title", "summary": "Translated summary"}
        self.translator = FakeTranslator()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def ingest(self, events):
        self.store.ingest(events, TODAY, next_month(TODAY))

    def test_partial_send_only_retries_failed_language(self):
        self.ingest([event()])
        snapshots = []
        sent, failures = publish_pending(self.store, self.config, self.translator, self.telegram,
            TODAY, lambda _: snapshots.append(1), time.monotonic() + 10)
        self.assertEqual((sent, failures), (1, 1))
        self.assertTrue(snapshots)
        self.assertEqual(self.store.pending(TODAY, ["ru", "en"], HASHES)[0][2], ["en"])

    def test_failed_checkpoint_stops_further_sends(self):
        self.ingest([event()])
        def checkpoint(_):
            raise RuntimeError("Upload failed")
        with self.assertRaisesRegex(RuntimeError, "Upload failed"):
            publish_pending(self.store, self.config, self.translator, self.telegram,
                            TODAY, checkpoint, time.monotonic() + 10)
        self.assertEqual(self.telegram.calls, [("ru", None)])

    def test_quota_failure_leaves_both_languages_pending(self):
        self.ingest([event()])
        class Quota:
            def translate(self, event, language):
                raise TranslationUnavailable()
        self.assertEqual(publish_pending(self.store, self.config, Quota(), self.telegram,
            TODAY, lambda _: None, time.monotonic() + 10), (0, 1))
        self.assertEqual(self.store.pending(TODAY, ["ru", "en"], HASHES)[0][2], ["ru", "en"])


class ReleaseTests(unittest.TestCase):
    def test_immutable_snapshots_restore_latest_language_receipt(self):
        class Http:
            assets = []
            contents = {}
            def request(self, url, **kwargs):
                if "/tags/" in url:
                    return {"id": 1, "upload_url": "https://uploads.example.org/assets{?name}"}
                if url.startswith("https://uploads.example.org"):
                    content = kwargs["body"]
                    name = url.split("?name=")[1]
                    asset = {"id": len(self.assets) + 1, "name": name,
                             "state": "uploaded", "size": len(content),
                             "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                             "url": "https://download.example.org/" + name}
                    self.assets.append(asset)
                    self.contents[asset["url"]] = content
                    return asset
                if "?per_page" in url:
                    return self.assets
                return self.contents[url]
        http = Http()
        remote = ReleaseState(http, "fake", "owner/repo")
        remote.release = remote.find_release()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "original.db")
            item = event()
            store.ingest([item], TODAY, next_month(TODAY))
            remote.checkpoint(store)
            key = store.pending(TODAY, ["ru", "en"], HASHES)[0][0]
            store.mark_published(key, "ru", HASHES["ru"], 123, item.fingerprint)
            remote.checkpoint(store)
            remote.checkpoint(store)  # No upload for unchanged state.
            self.assertEqual(len(http.assets), 2)
            self.assertNotEqual(http.assets[0]["name"], http.assets[1]["name"])
            restored_path = Path(directory) / "restored.db"
            remote.restore(restored_path)
            restored = Store(restored_path)
            self.assertEqual(restored.pending(TODAY, ["ru", "en"], HASHES)[0][2], ["en"])
            restored.close()
            store.close()

    def test_missing_release_requires_explicit_initialization(self):
        class Http:
            def request(self, url, **kwargs):
                raise RemoteError("GitHub", 404)
        remote = ReleaseState(Http(), "fake", "owner/repo")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            with self.assertRaisesRegex(RuntimeError, "missing"):
                remote.restore(path)
            remote.restore(path, initialize=True)
            self.assertFalse(path.exists())

    def test_existing_release_download_failure_never_resets(self):
        class Http:
            def request(self, url, **kwargs):
                if "/tags/" in url:
                    return {"id": 1}
                if "?per_page" in url:
                    return [{"name": "events-20261005T090000000000Z-12345678.db", "url": "https://example.org/snapshot"}]
                raise RemoteError("GitHub", 503)
        remote = ReleaseState(Http(), "fake", "owner/repo")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            with self.assertRaises(RemoteError):
                remote.restore(path, initialize=True)
            self.assertFalse(path.exists())


class FormattingTests(unittest.TestCase):
    def test_month_boundary(self):
        self.assertEqual(next_month(date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(next_month(date(2026, 12, 15)), date(2027, 1, 15))

    def test_source_html_is_escaped(self):
        message = build_message(event(), {"title": "<b>Title</b>", "summary": "A & B"}, "en", TODAY)
        self.assertIn("&lt;b&gt;Title&lt;/b&gt;", message)
        self.assertIn("A &amp; B", message)
        self.assertIn("20.10.2026 19:00", message)

    def test_schedule_shows_dates_not_fake_midnight_times(self):
        message = build_message(event(date_only=True), {"title": "Title", "summary": "Summary"}, "ru", TODAY)
        self.assertNotIn("19:00", message)
        self.assertIn("20.10.2026", message)

    def test_translation_response_validation(self):
        class Http:
            def request(self, url, **kwargs):
                return {"message": {"content": '{"title": "", "summary": "Something"}'}}
        translator = Translator(Http(), load_config()["ollama"], "fake")
        self.assertRaises(ValueError, translator.translate, event(), "en")

    def test_unchanged_edit_is_successful(self):
        class Http:
            def request(self, url, **kwargs):
                raise RemoteError("Telegram", 400, description="Bad Request: message is not modified: text unchanged")
        telegram = Telegram(Http(), "fake", {"ru": "ru", "en": "en"})
        self.assertEqual(telegram.publish("ru", "Same message", 42), 42)


if __name__ == "__main__":
    unittest.main()
