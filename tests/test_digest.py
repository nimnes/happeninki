import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from happeninki.__main__ import run
from happeninki.config import load_config
from happeninki.digest import build_digest, next_week, preview_digest, publish_digest, shortlist
from happeninki.http import RemoteError
from happeninki.models import Event, next_month
from happeninki.store import Store
from happeninki.telegram import channel_hash

SUNDAY = date(2026, 10, 11)


def event(number=1, **changes):
    result = Event(source='tampere', source_id=str(number), title=f'Concert {number}', description='A jazz concert.',
                   url=f'https://example.com/events/{number}', municipality='Tampere', venue='G Livelab',
                   address='G Livelab, Puutarhakatu 1', category='music', source_categories=['music'],
                   start='2026-10-15T19:00:00+03:00', end='2026-10-15T21:00:00+03:00', dates=[])
    return replace(result, **changes)


class Translator:
    def __init__(self):
        self.calls = []

    def translate(self, event, language):
        self.calls.append((event.source_id, language))
        return {'title': event.title, 'summary': 'A short event description.'}


class Telegram:
    channels = {'ru': 'ru', 'en': 'en'}

    def __init__(self):
        self.calls = []

    def publish(self, language, message):
        self.calls.append((language, message))
        return len(self.calls)


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'events.db'
        self.store = Store(self.path)
        self.config = load_config()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def publish(self, events, translator=None, telegram=None, checkpoint=lambda _: None):
        return publish_digest(events, self.config, SUNDAY, self.store, translator, telegram or Telegram(),
                              checkpoint, time.monotonic() + 600)

    def test_calendar_weeks_include_year_boundary(self):
        self.assertEqual(next_week(SUNDAY), (date(2026, 10, 12), date(2026, 10, 18)))
        self.assertEqual(next_week(date(2026, 12, 27)), (date(2026, 12, 28), date(2027, 1, 3)))
        self.assertEqual(next_week(date(2026, 10, 12))[0], date(2026, 10, 19))

    def test_top_ten_use_preferences_and_remove_duplicates(self):
        entries = [event(i) for i in range(12)]
        entries += [event(20, title='Kuoro: Mozartin Requiem', venue='Tuomiokirkko', address='Tuomiokirkko'),
                    event(21, title=event(1).title, end='2026-10-15T22:00:00+03:00'),
                    event(22, cancelled=True), event(23, title='Standup night'),
                    event(24, title='Kuorokonsertti', venue='Kalevan kirkko', address='Kalevan kirkko'),
                    event(25, start='2026-10-19', end='2026-10-19'),
                    event(26, start='2026-10-11', end='2026-10-11')]
        ranked = shortlist(entries, self.config, SUNDAY, 'ru')
        self.assertEqual(len(ranked), 10)
        self.assertEqual(ranked[0][0].source_id, '20')
        self.assertEqual(len({item.title for item, _ in ranked}), 10)
        self.assertFalse({'21', '22', '23', '24', '25', '26'} & {item.source_id for item, _ in ranked})

    def test_exhibitions_and_per_language_delivery(self):
        exhibition = event(2, title='Museum exhibition', category='exhibitions', source_categories=['exhibitions'],
                           date_only=True, start='2026-10-01', end='2026-10-30')
        russian = event(3, delivery_languages=['ru'])
        english = shortlist([exhibition, russian], self.config, SUNDAY, 'en')
        self.assertEqual(len(english), 1)
        self.assertEqual((english[0][0].start, english[0][0].end), ('2026-10-12', '2026-10-18'))
        self.assertEqual(exhibition.start, '2026-10-01')
        self.assertEqual(len(shortlist([exhibition, russian], self.config, SUNDAY, 'ru')), 2)
        self.config['sources']['tampere']['enabled'] = False
        self.assertEqual(shortlist([exhibition], self.config, SUNDAY, 'en'), [])

    def test_recurring_occurrences_are_projected_into_week(self):
        dates = [{'start': f'2026-10-{day}T19:00:00+03:00', 'end': f'2026-10-{day}T21:00:00+03:00'}
                 for day in ('04', '15', '21')]
        original = event(start=dates[0]['start'], end=dates[-1]['end'], dates=dates)
        selected = shortlist([original], self.config, SUNDAY, 'en')[0][0]
        self.assertEqual(selected.dates, [dates[1]])
        self.assertEqual(original.dates, dates)

    def test_message_is_linked_escaped_and_fits_one_post(self):
        start, end = next_week(SUNDAY)
        entries = [(event(i, url=f'https://example.com/events/{i}?a=1&b=2'),
                    {'title': '<Name & name> ' * 30, 'summary': '🎵 Music & culture. ' * 100}) for i in range(10)]
        message, count = build_digest(entries, 'en', start, end)
        self.assertEqual(count, 10)
        self.assertEqual(message.count('<a href='), 10)
        self.assertIn('?a=1&amp;b=2', message)
        self.assertIn('&lt;Name', message)
        self.assertLessEqual(len(message.encode('utf-16-le')) // 2, 4096)
        self.assertIn('12.10.2026–18.10.2026', message)

    def test_huge_links_reduce_count_instead_of_splitting_messages(self):
        start, end = next_week(SUNDAY)
        entries = [(event(i, url='https://example.com/' + 'x' * 1000), {'title': 'Event', 'summary': 'Summary'}) for i in range(10)]
        message, count = build_digest(entries, 'ru', start, end)
        self.assertTrue(0 < count < 10)
        self.assertLessEqual(len(message.encode('utf-16-le')) // 2, 4096)

    def test_database_includes_posted_baseline_but_not_suppressed_events(self):
        events = [event(1), event(2)]
        self.store.ingest(events, SUNDAY, next_month(SUNDAY))
        event_id = self.store.pending(SUNDAY, ['ru'], {'ru': channel_hash('ru')})[0][0]
        self.store.mark_published(event_id, 'ru', channel_hash('ru'), 123, events[0].fingerprint)
        with self.store.connection:
            self.store.connection.execute('UPDATE events SET eligible=0')
        self.store.reconcile_selection('tampere', [events[0]], SUNDAY, next_month(SUNDAY))
        self.assertEqual([item.source_id for item in self.store.digest_events()], ['1'])
        self.assertEqual(len(shortlist(self.store.digest_events(), self.config, SUNDAY, 'ru')), 1)

    def test_one_message_per_channel_reuses_translations_and_survives_reset(self):
        events = [event(i) for i in range(12)]
        self.store.ingest(events, SUNDAY, next_month(SUNDAY))
        translator, telegram = Translator(), Telegram()
        self.assertEqual(self.publish(events, translator, telegram), (2, 0))
        self.assertEqual(len(telegram.calls), 2)
        self.assertEqual(len(translator.calls), 20)
        self.assertEqual(self.store.quota_used(SUNDAY, channel_hash('ru')), 0)
        self.assertEqual(self.publish(events, translator, telegram), (0, 0))
        self.store.close()
        self.store = Store(self.path)
        self.store.reset()
        self.assertEqual(self.publish(events, translator, telegram), (0, 0))
        self.assertEqual(len(telegram.calls), 2)

    def test_cached_translations_allow_digest_without_model_access(self):
        for language in ('ru', 'en'):
            self.store.cache_translation(event(), language, {'title': 'Event', 'summary': 'Summary'})
        self.assertEqual(self.publish([event()], telegram=Telegram()), (2, 0))

    def test_empty_digest_does_not_post(self):
        telegram = Telegram()
        self.assertEqual(self.publish([], Translator(), telegram), (0, 0))
        self.assertEqual(telegram.calls, [])

    def test_uncertain_digest_is_held_across_restart_and_can_be_resolved(self):
        class Sender(Telegram):
            channels = {'ru': 'ru'}
            def publish(self, language, message):
                self.calls.append((language, message))
                raise TimeoutError('Unknown outcome')
        telegram = Sender()
        self.assertEqual(self.publish([event()], Translator(), telegram), (0, 1))
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.publish([event()], Translator(), telegram), (0, 1))
        self.assertEqual(len(telegram.calls), 1)
        holds = self.store.delivery_holds({'ru': channel_hash('ru')})
        self.assertEqual(holds[0]['source_key'], 'digest:2026-10-12')
        self.store.resolve_weekly_digest('2026-10-12', 'ru', channel_hash('ru'), 123)
        self.assertEqual(self.publish([event()], Translator(), telegram), (0, 0))

    def test_definite_rejection_can_retry_and_preserves_successful_channel(self):
        class Sender(Telegram):
            def publish(self, language, message):
                if language == 'en':
                    raise RemoteError('Telegram', 403)
                return super().publish(language, message)
        first = Sender()
        self.assertEqual(self.publish([event()], Translator(), first), (1, 1))
        second = Telegram()
        self.assertEqual(self.publish([event()], Translator(), second), (1, 0))
        self.assertEqual([language for language, _ in second.calls], ['en'])

    def test_lost_digest_receipt_checkpoint_restores_hold(self):
        self.store.ingest([event()], SUNDAY, next_month(SUNDAY))
        backup = Path(self.directory.name) / 'remote.db'
        telegram = Telegram()
        telegram.channels = {'ru': 'ru'}
        def checkpoint(store):
            row = store.weekly_digest('2026-10-12', 'ru', channel_hash('ru'))
            if row and row['status'] == 'sent':
                raise RuntimeError('Receipt upload failed')
            store.snapshot(backup)
        with self.assertRaisesRegex(RuntimeError, 'Receipt upload failed'):
            self.publish([event()], Translator(), telegram, checkpoint)
        self.store.close()
        self.path = backup
        self.store = Store(backup)
        self.assertEqual(self.publish([event()], Translator(), telegram), (0, 1))
        self.assertEqual(len(telegram.calls), 1)

    def test_digest_publish_reads_database_without_source_or_model_requests(self):
        self.store.ingest([event()], SUNDAY, next_month(SUNDAY))
        for language in ('ru', 'en'):
            self.store.cache_translation(event(), language, {'title': 'Event', 'summary': 'Summary'})
        args = SimpleNamespace(config='config.toml', mode='publish', weekly_digest=True, translate=False,
            release_state=False, database=str(self.path), initialize=False, reset_state=False,
            requeue_upcoming=False, limit=10, output='unused.json')
        telegram = Telegram()
        with patch('happeninki.__main__.collect', side_effect=AssertionError('No source fetches')), \
                patch('happeninki.__main__.Translator', side_effect=AssertionError('Use cached translations')), \
                patch('happeninki.__main__.Telegram', return_value=telegram), \
                patch('happeninki.__main__.datetime') as clock, \
                patch.dict('os.environ', {'TELEGRAM_CHANNEL_RU': 'ru', 'TELEGRAM_CHANNEL_EN': 'en', 'OLLAMA_API_KEY': ''}):
            clock.now.return_value = datetime.fromisoformat('2026-10-11T18:00:00+03:00')
            self.assertEqual(run(args), 0)
        self.assertEqual(len(telegram.calls), 2)
        self.assertEqual(len(self.store.pending(SUNDAY, ['ru', 'en'], {'ru': channel_hash('ru'), 'en': channel_hash('en')})), 1)

    def test_digest_preview_reads_database_without_collection_or_mutation(self):
        self.store.ingest([event()], SUNDAY, next_month(SUNDAY))
        output = Path(self.directory.name) / 'digest.json'
        args = SimpleNamespace(config='config.toml', mode='preview', weekly_digest=True, translate=False,
            release_state=False, database=str(self.path), initialize=False, reset_state=False,
            requeue_upcoming=False, limit=10, output=str(output))
        with patch('happeninki.__main__.collect', side_effect=AssertionError('No source requests allowed')), \
                patch('happeninki.__main__.datetime') as clock, patch.dict('os.environ', {'TELEGRAM_CHANNEL_RU': '', 'TELEGRAM_CHANNEL_EN': ''}):
            clock.now.return_value = datetime.fromisoformat('2026-10-11T18:00:00+03:00')
            self.assertEqual(run(args), 0)
        preview = json.loads(output.read_text())
        self.assertEqual(preview['week_start'], '2026-10-12')
        self.assertEqual(preview['channels']['ru']['included_events'], 1)
        self.assertTrue(preview['channels']['ru']['untranslated_source_fallback'])
        self.assertIsNone(self.store.weekly_digest('2026-10-12', 'ru', channel_hash('ru')))
        self.assertIsNone(self.store.translation(event(), 'ru'))

    def test_digest_publish_is_not_due_on_other_days(self):
        args = SimpleNamespace(config='config.toml', mode='publish', weekly_digest=True)
        with patch('happeninki.__main__.datetime') as clock, patch('happeninki.__main__.collect') as collect:
            clock.now.return_value = datetime.fromisoformat('2026-10-10T18:00:00+03:00')
            self.assertEqual(run(args), 0)
            collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
