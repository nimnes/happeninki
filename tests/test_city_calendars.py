import copy
import unittest
from datetime import date

from happeninki.config import load_config
from happeninki.linked_events import HelsinkiSource, parse_linked_event
from happeninki.turku import TurkuSource, parse_turku


class CityCalendarTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.helsinki = {'id': 'test:1', 'name': {'fi': 'Aikuisten näytelmä'},
                        'description': {'fi': 'Esitys aikuisille.'},
                        'start_time': '2026-12-05T18:00:00Z', 'end_time': '2026-12-05T20:00:00Z',
                        'in_language': [{'@id': 'https://api.hel.fi/linkedevents/v1/language/ru/'}],
                        'location': {'name': {'fi': 'Sali'}, 'address_locality': {'fi': 'Helsinki'}}}
        self.turku = {'_id': 'test1', 'pageType': 'event', 'name': 'Aikuisten esitys',
                      'descriptionLong': 'Esityskieli: venäjä.', 'globalContentCategories': ['Theatre'],
                      'locations': [{'address': 'Sali, Turku'}],
                      'event': {'dates': [{'start': '2026-12-05T18:00:00Z', 'end': '2026-12-05T20:00:00Z'}]}}

    def test_language_evidence_and_city_required(self):
        event = parse_linked_event(self.helsinki, self.config)
        self.assertEqual(event.delivery_languages, ['ru'])
        self.assertEqual(event.start, '2026-12-05T20:00:00+02:00')
        self.helsinki['in_language'] = []
        self.helsinki['name']['ru'] = 'Русское описание'
        self.assertIsNone(parse_linked_event(self.helsinki, self.config))
        self.helsinki['in_language'] = [{'id': 'ru'}]
        self.helsinki['location']['address_locality']['fi'] = 'Espoo'
        self.assertIsNone(parse_linked_event(self.helsinki, self.config))

    def test_turku_actual_language_not_translation_or_artist_origin(self):
        event = parse_turku(self.turku, self.config)
        self.assertEqual(event.municipality, 'Turku')
        self.assertEqual(event.source, 'turku')
        self.assertEqual(event.delivery_languages, ['ru'])
        self.assertIn('kalenteri.turku.fi', event.url)
        for description in ['Russian artist performing in Finnish.', 'Описание на русском.', 'Not performed in Russian.']:
            self.turku['descriptionLong'] = description
            self.turku['inLanguage'] = 'ru'
            self.assertIsNone(parse_turku(self.turku, self.config))

    def test_exclusions_remain_and_touring_city_added(self):
        self.helsinki['name'] = {'fi': 'Lasten esitys'}
        self.assertIsNone(parse_linked_event(self.helsinki, self.config))
        self.turku['name'] = 'Мастер-класс на русском языке'
        self.assertIsNone(parse_turku(self.turku, self.config))
        self.assertIn('Turku', self.config['sources']['art_master']['municipalities'])
        self.assertNotIn('Turku', self.config['municipalities'])

    def test_helsinki_pagination_and_recurring_parent(self):
        parent = dict(self.helsinki, super_event_type='recurring')
        pages = [{'data': [parent], 'meta': {'next': 'https://api.hel.fi/linkedevents/v1/event/?page=2'}},
                 {'data': [self.helsinki], 'meta': {'next': None}}]
        class Http:
            def request(_, url, **kwargs):
                return pages.pop(0)
        events = HelsinkiSource(self.config, Http()).fetch(date(2026, 12, 1), date(2026, 12, 31))
        self.assertEqual(len(events), 1)
        self.assertEqual(pages, [])

    def test_turku_splits_capped_results_and_merges_dates(self):
        second = copy.deepcopy(self.turku)
        second['event']['dates'][0] = {'start': '2026-12-06T18:00:00Z', 'end': '2026-12-06T20:00:00Z'}
        responses = [{'pages': [{}] * 500}, {'pages': [self.turku]}, {'pages': [second]}]
        class Http:
            def request(_, url, **kwargs):
                return responses.pop(0)
        events = TurkuSource(self.config, Http()).fetch(date(2026, 12, 5), date(2026, 12, 6))
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0].dates), 2)
        self.assertEqual(events[0].end, '2026-12-06T22:00:00+02:00')

    def test_small_local_events_rejected_even_at_major_venue(self):
        for title, description in [('Pelmeni Club', 'Досуговый кружок для молодёжи.'),
                                   ('Community theatre play', 'Amateur theatre production.'),
                                   ('Russian conversation club', 'Weekly local meeting.')]:
            with self.subTest(title=title):
                self.helsinki['name'] = {'en': title}
                self.helsinki['description'] = {'en': description}
                self.helsinki['location']['name'] = {'fi': 'Musiikkitalo'}
                self.assertIsNone(parse_linked_event(self.helsinki, self.config))

    def test_stage_plays_and_musicals_remain_eligible(self):
        for title in ['Русский спектакль', 'Большой мюзикл', 'Touring stage play']:
            self.helsinki['name'] = {'ru': title}
            self.assertIsNotNone(parse_linked_event(self.helsinki, self.config))

    def test_concert_requires_major_venue_and_reaches_publication_threshold(self):
        from happeninki.selection import score_event
        self.helsinki['name'] = {'ru': 'Большой концерт'}
        self.helsinki['keywords'] = [{'name': {'en': 'music'}}]
        for venue in ['Neighbourhood library', 'Musiikkitalo, small hall', 'Logomo foyer']:
            self.helsinki['location']['name'] = {'en': venue}
            self.assertIsNone(parse_linked_event(self.helsinki, self.config))
        self.helsinki['location']['name'] = {'fi': 'Savoy-teatteri'}
        event = parse_linked_event(self.helsinki, self.config)
        self.assertIsNotNone(event)
        score, _ = score_event(event, self.config, date(2026, 11, 20))
        self.assertGreaterEqual(score, self.config['selection']['minimum_score'])
        self.helsinki['name'] = {'en': 'Neighbourhood gathering'}
        self.helsinki['keywords'] = []
        self.assertIsNone(parse_linked_event(self.helsinki, self.config))

    def test_turku_major_concert_uses_destination_venues(self):
        self.turku.update(name='Концерт', descriptionLong='Performed in Russian.', globalContentCategories=['Music'])
        self.turku['locations'] = [{'address': 'Logomo, Turku'}]
        self.assertIsNotNone(parse_turku(self.turku, self.config))
        self.turku['locations'] = [{'address': 'Local cafe, Turku'}]
        self.assertIsNone(parse_turku(self.turku, self.config))
