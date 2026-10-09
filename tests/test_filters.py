import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from happeninki.__main__ import publish_pending
from happeninki.config import load_config
from happeninki.filters import exclusion_reason
from happeninki.models import Event, next_month
from happeninki.sources import parse_tampere
from happeninki.store import Store
from happeninki.telegram import channel_hash


TODAY = date(2026, 10, 7)
HASHES = {language: channel_hash(language) for language in ("ru", "en")}


def event(**kwargs):
    values = dict(source="tampere", source_id="one", title="Concert", description="Music",
                  url="https://example.org/event", municipality="Tampere", venue="Venue",
                  address="Venue, Street 1", category="music", start="2026-10-20", end="2026-10-20", dates=[])
    values.update(kwargs)
    return Event(**values)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config["filters"]["music_selection"] = "all"

    def reason(self, title, description="", tags=()):
        return exclusion_reason(title, description, tags, self.config)

    def page(self, title, tags, description=""):
        path = Path(__file__).parent / "fixtures/tampere-individual-dates.json"
        page = json.loads(path.read_text())
        page.update(name=title, globalContentCategories=tags, descriptionLong=description, descriptionShort=description)
        return page

    def test_child_tag_overrides_music_and_exhibition(self):
        self.assertIsNotNone(self.reason("Concert", tags=["music", "kids and family"]))
        self.assertIsNotNone(self.reason("Exhibition", tags=["exhibitions", "kids and family"]))
        self.assertIsNotNone(self.reason("Lasten konsertti", tags=["music"]))
        self.assertIsNotNone(self.reason("Craft afternoon", "Tapahtuma on suunnattu lapsille."))

    def test_daycare_exhibition_without_child_tags_is_excluded(self):
        description = ("Ystävyys on seikkailu on Hervantalaisten yksityisten perhepäivähoitajien "
                       "yhdessä toteuttama projekti, jossa lapset kokevat jännittävän seikkailun "
                       "Pupun ja Ketun kanssa käyttäen musiikkia, liikettä ja kädentaitoja.")
        tags = ["museums and galleries", "museums", "exhibitions"]
        self.assertEqual(self.reason("Ystävyys on seikkailu", description, tags), "children's activities")
        self.assertIsNone(parse_tampere(self.page("Ystävyys on seikkailu", tags, description),
                                       "Tampere", self.config))
        self.config["filters"]["exclude_children"] = False
        self.assertIsNone(self.reason("Ystävyys on seikkailu", description, tags))

    def test_daycare_mention_alone_does_not_exclude_adult_exhibition(self):
        self.assertIsNone(self.reason("Valokuvanäyttely", "Kuvia kaupungista ja sen päiväkodeista.",
                                      ["exhibitions"]))

    def test_user_linked_examples_are_excluded(self):
        config = load_config()
        pages = json.loads((Path(__file__).parent / "fixtures/tampere-preference-examples.json").read_text())
        self.assertEqual(len(pages), 4)
        for page in pages:
            with self.subTest(title=page["name"]):
                self.assertIsNone(parse_tampere(page, "Tampere", config))

    def test_new_format_exclusions_override_concert_tags(self):
        for title, description in (("Luentokonserttisarja: 540 vuotta kitaran historiaa", ""),
                                   ("Comedy night", "Stand-up comedy"),
                                   ("Friday", "Club night with DJ sets")):
            self.assertIsNotNone(self.reason(title, description, ["consert"]))
        for key, title in (("exclude_lectures", "Lecture"), ("exclude_standup", "Stand-up"),
                           ("exclude_nightclubs", "Club night")):
            self.config["filters"][key] = False
            self.assertIsNone(self.reason(title))

    def test_family_show_without_child_tag_is_excluded(self):
        self.assertIsNotNone(self.reason("Show", "Koko perheelle sopiva esitys", ["culture"]))
        self.assertIsNotNone(self.reason("Show", "Lasten konsertti kirjastossa", ["music"]))
        self.assertIsNone(self.reason("Adult concert", "Lastenliput 10 euroa", ["music"]))

    def test_child_age_and_untagged_theatre(self):
        self.assertIsNotNone(self.reason("Tanssiteatteri MD: Tanssiva Muumilaakso",
                                        "Suositusikä yli 3-vuotiaille", ["culture", "dance"]))
        self.assertIsNotNone(self.reason("Eliisa-teatteri: Augusta", "Esitys suomeksi", ["consert"]))
        self.assertIsNone(self.reason("Adult concert", "Ikäraja 18 vuotta", ["music"]))
        self.assertIsNone(self.reason("Adult concert", "Children under 7 enter free", ["music"]))

    def test_curated_music_and_nightclub_venues(self):
        self.config["filters"]["music_selection"] = "curated"
        self.assertIsNone(exclusion_reason("Headline concert", "", ["music"], self.config,
                                          venue="Nokia Arena, Kansikatu 3"))
        self.assertIsNotNone(exclusion_reason("Local performer", "", ["consert"], self.config,
                                              venue="Kalevan Kulma"))
        self.config["filters"]["music_artists"] = ["Favourite Band"]
        self.assertIsNone(self.reason("Favourite Band live", tags=["music"]))
        self.assertIsNotNone(self.reason("Not Favourite Bandit", tags=["music"]))
        self.assertIsNotNone(exclusion_reason("Favourite Band live", "", ["music"], self.config,
                                              venue="Fame Club"))
        self.assertIsNone(parse_tampere(self.page("Local performer", ["consert"]),
                                       "Tampere", self.config))

    def test_reading_activities_and_dogs(self):
        for title in ("Lukupiiri", "Lukukoiralle lukeminen", "Lue koiralle", "Kirjakerho",
                      "Reading to a dog", "Book club", "Satutuokio"):
            with self.subTest(title=title):
                self.assertIsNotNone(self.reason(title))
        self.assertIsNotNone(self.reason("Author evening", tags=["literature"]))

    def test_general_courses_workshops_and_games_excluded(self):
        for title in ("Lasten tanssikurssit", "Valokuvauskurssi", "English language course",
                      "Keramiikkatyöpaja", "Craft workshop", "Bingo", "Pub Quiz", "Karaoke"):
            with self.subTest(title=title):
                self.assertIsNotNone(self.reason(title))

    def test_theatre_requires_explicit_english_performance(self):
        for description in ("", "Esitys on suomeksi.", "A famous play by Shakespeare.",
                            "English subtitles available.", "Performed in Finnish with English surtitles.",
                            "Not performed in English."):
            with self.subTest(description=description):
                self.assertIsNotNone(self.reason("Hamlet", description, ["theatre"]))
        for description in ("Performed in English.", "The play is in English.",
                            "Esityskieli: englanti.", "Esitys esitetään englanniksi.",
                            "Englanninkielinen näytelmä.", "English-language performance."):
            with self.subTest(description=description):
                self.assertIsNone(self.reason("Hamlet", description, ["theatre"]))
        self.assertIsNone(self.reason("Hamlet (in English)", tags=["theatre"]))

    def test_theatre_filter_scoped_and_optional(self):
        self.assertIsNone(self.reason("Concert", "Esitys on suomeksi.", ["music"]))
        self.assertIsNotNone(self.reason("Uusi näytelmä", tags=["culture"]))
        self.config["filters"]["theatre_languages"] = []
        self.assertIsNone(self.reason("Hamlet", tags=["theatre"]))

    def test_russian_theatre_allowed_but_subtitles_are_not_enough(self):
        for description in ("Performed in Russian.", "Esityskieli: venäjä.",
                            "Esitys esitetään venäjäksi.", "Venäjänkielinen näytelmä.",
                            "Спектакль на русском языке.", "Язык спектакля: русский.",
                            "Not performed in English. Performed in Russian."):
            with self.subTest(description=description):
                self.assertIsNone(self.reason("Hamlet", description, ["theatre"]))
        for description in ("Russian subtitles available.", "Not performed in Russian.",
                            "Спектакль на финском языке. Субтитры на русском языке."):
            self.assertIsNotNone(self.reason("Hamlet", description, ["theatre"]))
        self.config["filters"]["theatre_languages"] = ["en"]
        self.assertIsNotNone(self.reason("Hamlet", "Performed in Russian.", ["theatre"]))

    def test_listing_language_does_not_establish_performance_language(self):
        page = self.page("Hamlet", ["theatre"], "A famous Finnish production.")
        page.update(inLanguage="en", languages=["fi", "en"])
        self.assertIsNone(parse_tampere(page, "Tampere", self.config))
        page["descriptionLong"] = "Performed in English."
        self.assertIsNotNone(parse_tampere(page, "Tampere", self.config))

    def test_finnish_learning_included_without_culture_tag(self):
        for title, description in (("Suomen kielen kurssi", ""), ("Finnish language course", ""),
                ("Puhutaan suomea", ""), ("Kielikahvila", "Harjoitellaan suomea yhdessä.")):
            with self.subTest(title=title):
                parsed = parse_tampere(self.page(title, ["seminars and meetings"], description), "Tampere", self.config)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.category, "language_learning")

    def test_finnish_learning_exception_is_scoped(self):
        self.assertIsNotNone(self.reason("Suomen kielen kurssi", tags=["kids and family"]))
        self.assertIsNotNone(self.reason("Maalauskurssi", "Opetus on suomen kielellä."))
        self.config["filters"]["allow_finnish_learning"] = False
        self.assertIsNotNone(self.reason("Suomen kielen kurssi"))

    def test_library_concert_and_exhibition_are_kept(self):
        for title, tags in (("Konsertti kirjastossa", ["music"]), ("Valokuvanäyttely", ["exhibitions"])):
            self.assertIsNone(self.reason(title, "Lapset alle 7 vuotta pääsevät ilmaiseksi.", tags))
            self.assertIsNotNone(parse_tampere(self.page(title, tags), "Tampere", self.config))

    def test_filters_can_be_disabled_and_customized(self):
        self.config["filters"]["exclude_games"] = False
        self.assertIsNone(self.reason("Bingo"))
        self.config["filters"]["exclude_reading"] = False
        self.assertIsNone(self.reason("Book club", tags=["literature"]))
        self.config["filters"]["exclude_title_keywords"] = ["open mic"]
        self.assertIsNotNone(self.reason("Friday OPEN MIC"))
        self.config["filters"]["excluded_source_categories"] = ["dance"]
        self.assertIsNotNone(self.reason("Evening performance", tags=["dance"]))

    def test_category_metadata_does_not_change_publication_fingerprint(self):
        item = event()
        self.assertEqual(item.fingerprint, replace(item, source_categories=["music"]).fingerprint)

    def test_invalid_preferences_rejected(self):
        content = Path("config.toml").read_text().replace("exclude_children = true", 'exclude_children = "yes"')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(content)
            with self.assertRaisesRegex(ValueError, "filters.exclude_children"):
                load_config(path)


class QueuePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "events.db")
        self.config = load_config()
        self.config["filters"]["music_selection"] = "all"

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_old_queued_child_event_suppressed_and_receipt_preserved(self):
        concert = event()
        child = event(source_id="child", title="Ambiguous title")
        self.store.ingest([concert, child], TODAY, next_month(TODAY))
        child_id = next(row[0] for row in self.store.pending(TODAY, ["ru"], HASHES) if row[1].source_id == "child")
        self.store.mark_published(child_id, "ru", HASHES["ru"], 99, child.fingerprint)
        self.store.reconcile_selection("tampere", [concert], TODAY, next_month(TODAY))
        self.assertEqual([row[1].source_id for row in self.store.pending(TODAY, ["ru", "en"], HASHES)], ["one"])
        self.assertEqual(self.store.publication(child_id, "ru", HASHES["ru"])["message_id"], 99)
        self.store.reconcile_selection("tampere", [concert, child], TODAY, next_month(TODAY))
        restored = next(row for row in self.store.pending(TODAY, ["ru", "en"], HASHES) if row[1].source_id == "child")
        self.assertEqual(restored[2], ["en"])

    def test_legacy_payload_without_tags_still_loads(self):
        item = event(title="Bingo")
        self.store.ingest([item], TODAY, next_month(TODAY))
        row = self.store.connection.execute("SELECT id, payload FROM events").fetchone()
        payload = json.loads(row["payload"])
        payload.pop("source_categories")
        with self.store.connection:
            self.store.connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
        self.assertEqual(self.store.pending(TODAY, ["ru"], HASHES)[0][1].source_categories, [])
        class NeverTranslate:
            def translate(self, event, language):
                raise AssertionError("Excluded event must not consume translation allowance")
        class NeverSend:
            channels = {"ru": "ru"}
            def publish(self, *args):
                raise AssertionError("Excluded event must not be sent")
        self.assertEqual(publish_pending(self.store, self.config, NeverTranslate(), NeverSend(),
                         TODAY, lambda _: None, time.monotonic() + 10), (0, 0))

    def test_failed_source_cannot_publish_old_unfiltered_queue(self):
        self.store.ingest([event()], TODAY, next_month(TODAY))
        class Sender:
            channels = {"ru": "ru"}
        self.assertEqual(publish_pending(self.store, self.config, None, Sender(), TODAY,
                         lambda _: None, time.monotonic() + 10, blocked_sources={"tampere"}), (0, 0))
        self.assertEqual(len(self.store.pending(TODAY, ["ru"], HASHES)), 1)


if __name__ == "__main__":
    unittest.main()
