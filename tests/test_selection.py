import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

from happeninki.classifier import Classifier, comparison, validate
from happeninki.config import load_config
from happeninki.filters import exclusion_reason, venue_matches
from happeninki.models import Event, next_month
from happeninki.selection import rank_pending
from happeninki.store import Store
from happeninki.__main__ import publish_pending
from happeninki.telegram import channel_hash
from happeninki.translator import TranslationUnavailable
from happeninki.http import RemoteError

TODAY = date(2026, 10, 9)
HASHES = {'en': channel_hash('en'), 'ru': channel_hash('ru')}


def event(number=1, **changes):
    result = Event(source='tampere', source_id=str(number), title=f'Concert {number}', description='Jazz concert',
                   url='https://example.com/event', municipality='Tampere', venue='G Livelab',
                   address='G Livelab, Puutarhakatu 1', category='music', start='2026-10-20T19:00:00+03:00',
                   end='2026-10-20T21:00:00+03:00', dates=[], source_categories=['music'])
    return replace(result, **changes)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'state.db'
        self.store = Store(self.path)
        self.config = load_config()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def pending(self, events, today=TODAY):
        self.store.ingest(events, today, next_month(today))
        return self.store.pending(today, ['ru', 'en'], HASHES, include_updates=True)

    def test_venue_identity_and_regression_exclusions(self):
        self.assertFalse(venue_matches('Telakka, Tullikamarin aukio 3', ['Tullikamari']))
        self.assertFalse(venue_matches('Fake G LivelabX, Street 1', ['G Livelab']))
        self.assertTrue(venue_matches('Tullikamarin Pakkahuone, Street 1', ['Tullikamari']))
        self.assertTrue(exclusion_reason('Koululaisten leffaperjantai', '', ['movies'], self.config))
        self.assertTrue(exclusion_reason('Tootsie - musikaalikomedia', '', ['movies'], self.config))
        self.assertFalse(exclusion_reason('Asla Jo + Saga Olsson', 'Musiikki on raikas ja musikaalinen.', ['music'], self.config, venue='G Livelab'))
        self.assertFalse(exclusion_reason('Candomino', 'Nuorisokuoro laulaa klassista musiikkia', ['music'], self.config,
                                          venue='Tampereen tuomiokirkko, Street 1'))

    def test_ranking_prefers_church_and_deduplicates(self):
        regular = event()
        church = event(2, venue='Tuomiokirkko', address='Tuomiokirkko', description='Kuoro klassinen konsertti')
        duplicate = event(3, title=regular.title, end='2026-10-20T22:00:00+03:00')
        pending, decisions = rank_pending(self.store, self.pending([regular, church, duplicate]), self.config, TODAY, HASHES)
        self.assertEqual([item[1].source_id for item in pending], ['2', '1'])
        self.assertIn('duplicate', [item['status'] for item in decisions.values()])
        self.assertGreater(decisions[pending[0][0]]['score'], decisions[pending[1][0]]['score'])

    def test_overflow_expires_but_far_future_waits(self):
        pending = self.pending([event(), event(2, start='2026-12-01', end='2026-12-02')])
        # Requeue a far-future baseline listing for this test.
        self.store.requeue_upcoming([item for item in [event(2, start='2026-12-01', end='2026-12-02')]], TODAY, date(2027, 1, 1))
        pending = self.store.pending(TODAY, ['ru', 'en'], HASHES)
        rank_pending(self.store, pending, self.config, TODAY, HASHES)
        ranked, decisions = rank_pending(self.store, pending, self.config, TODAY + timedelta(days=3), HASHES)
        self.assertEqual(ranked, [])
        self.assertEqual({info['status'] for info in decisions.values()}, {'skipped', 'scheduled'})
        ranked, _ = rank_pending(self.store, pending, self.config, date(2026, 11, 3), HASHES)
        self.assertEqual([item[1].source_id for item in ranked], ['2'])

    def test_material_change_reopens_decision(self):
        pending = self.pending([event()])
        rank_pending(self.store, pending, self.config, TODAY, HASHES)
        self.assertEqual(rank_pending(self.store, pending, self.config, TODAY + timedelta(days=3), HASHES)[0], [])
        pending = self.pending([event(description='Updated jazz concert programme')], TODAY + timedelta(days=3))
        self.assertEqual(len(rank_pending(self.store, pending, self.config, TODAY + timedelta(days=3), HASHES)[0]), 1)

    def test_selected_translation_retries_survive_expiry_and_restart(self):
        self.pending([event()])
        class Translator:
            def translate(self, event, language):
                raise TranslationUnavailable()
        class Telegram:
            channels = {'ru': 'ru', 'en': 'en'}
            def publish(self, *args, **kwargs):
                raise AssertionError('Translation failed; no send allowed')
        result = publish_pending(self.store, self.config, Translator(), Telegram(), TODAY,
                                 lambda _: None, time.monotonic() + 30)
        self.assertEqual(result, (0, 1))
        self.store.close()
        self.store = Store(self.path)
        later = TODAY + timedelta(days=4)
        pending = self.store.pending(later, ['ru', 'en'], HASHES)
        ranked, _ = rank_pending(self.store, pending, self.config, later, HASHES)
        self.assertEqual(ranked[0][2], ['ru', 'en'])

    def test_legacy_partial_delivery_retries_after_expiry(self):
        pending = self.pending([event()])
        rank_pending(self.store, pending, self.config, TODAY, HASHES)
        self.store.mark_published(pending[0][0], 'ru', HASHES['ru'], 123, pending[0][1].fingerprint)
        later = TODAY + timedelta(days=4)
        pending = self.store.pending(later, ['ru', 'en'], HASHES)
        ranked, _ = rank_pending(self.store, pending, self.config, later, HASHES)
        self.assertEqual(ranked[0][2], ['en'])

    def test_definite_send_rejection_remains_retryable_after_expiry(self):
        self.pending([event()])
        class Translator:
            def translate(self, event, language):
                return {'title': event.title, 'summary': 'Jazz concert'}
        class Telegram:
            channels = {'ru': 'ru'}
            def publish(self, *args, **kwargs):
                raise RemoteError('Telegram', 403)
        result = publish_pending(self.store, self.config, Translator(), Telegram(), TODAY, lambda _: None, time.monotonic() + 30)
        self.assertEqual(result, (0, 1))
        self.assertEqual(self.store.delivery_holds(HASHES), [])
        actual_day = datetime.now(ZoneInfo(self.config['timezone'])).date()
        self.assertEqual(self.store.quota_used(actual_day, HASHES['ru']), 0)
        later = TODAY + timedelta(days=4)
        pending = self.store.pending(later, ['ru'], HASHES)
        self.assertEqual(len(rank_pending(self.store, pending, self.config, later, HASHES)[0]), 1)

    def test_recurring_notice_window_uses_next_occurrence(self):
        recurring = event(start='2026-09-01T19:00:00+03:00', end='2026-12-01T21:00:00+02:00', dates=[
            {'start': '2026-09-01T19:00:00+03:00', 'end': '2026-09-01T21:00:00+03:00'},
            {'start': '2026-12-01T19:00:00+02:00', 'end': '2026-12-01T21:00:00+02:00'}])
        fingerprint = recurring.fingerprint
        self.store.ingest([], TODAY, next_month(TODAY))
        pending = self.pending([recurring])
        ranked, decisions = rank_pending(self.store, pending, self.config, TODAY, HASHES)
        self.assertEqual(ranked, [])
        info = decisions[pending[0][0]]
        self.assertEqual(info['status'], 'scheduled')
        self.assertEqual(info['components']['timing'], 0)
        self.assertEqual(info['next_occurrence'], recurring.dates[1]['start'])
        ranked, decisions = rank_pending(self.store, pending, self.config, date(2026, 11, 3), HASHES)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(decisions[ranked[0][0]]['components']['timing'], 10)
        self.assertEqual(recurring.fingerprint, fingerprint)

    def test_finished_occurrence_today_does_not_open_future_notice_window(self):
        recurring = event(start='2026-10-09T08:00:00+03:00', end='2026-12-01T21:00:00+02:00', dates=[
            {'start': '2026-10-09T08:00:00+03:00', 'end': '2026-10-09T09:00:00+03:00'},
            {'start': '2026-12-01T19:00:00+02:00', 'end': '2026-12-01T21:00:00+02:00'}])
        pending = self.pending([recurring])
        ranked, decisions = rank_pending(self.store, pending, self.config, TODAY, HASHES,
                                         now=datetime.fromisoformat('2026-10-09T10:00:00+03:00'))
        self.assertEqual(ranked, [])
        self.assertEqual(decisions[pending[0][0]]['status'], 'scheduled')

    def test_ongoing_exhibition_remains_eligible(self):
        pending = self.pending([event(category='exhibitions', source_categories=['exhibitions'], date_only=True,
                                      start='2026-09-01', end='2026-12-01')])
        ranked, decisions = rank_pending(self.store, pending, self.config, TODAY, HASHES)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(decisions[ranked[0][0]]['components']['timing'], 10)

    def test_posted_updates_bypass_rejection_and_suppression(self):
        pending = self.pending([event()])
        event_id = pending[0][0]
        self.store.mark_published(event_id, 'ru', HASHES['ru'], 123, pending[0][1].fingerprint)
        changed = event(title='Cancelled standup', cancelled=True)
        pending = self.pending([changed])
        self.store.reconcile_selection('tampere', [], TODAY, next_month(TODAY))
        pending = self.store.pending(TODAY, ['ru', 'en'], HASHES, include_updates=True)
        ranked, _ = rank_pending(self.store, pending, self.config, TODAY, HASHES)
        self.assertEqual(ranked[0][2], ['ru'])

    def test_cancellation_still_updates_after_changed_dates_have_passed(self):
        pending = self.pending([event()])
        event_id = pending[0][0]
        self.store.mark_published(event_id, 'ru', HASHES['ru'], 123, pending[0][1].fingerprint)
        self.pending([event(cancelled=True, start='2026-10-08', end='2026-10-08')])
        pending = self.store.pending(TODAY, ['ru', 'en'], HASHES, include_updates=True)
        self.assertEqual(pending[0][2], ['ru'])

    def test_additive_migration_preserves_receipts(self):
        pending = self.pending([event()])
        self.store.mark_published(pending[0][0], 'ru', HASHES['ru'], 123, pending[0][1].fingerprint)
        with self.store.connection:
            for table in ('classifications', 'editorial', 'daily_posts'):
                self.store.connection.execute(f'DROP TABLE {table}')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.publication(pending[0][0], 'ru', HASHES['ru'])['message_id'], 123)
        self.assertEqual(self.store.pending(TODAY, ['ru', 'en'], HASHES)[0][2], ['en'])

    def test_uncertain_transport_send_keeps_persistent_slot(self):
        self.pending([event()])
        class Translator:
            def translate(self, event, language):
                return {'title': event.title, 'summary': 'Jazz concert'}
        class Telegram:
            channels = {'ru': 'ru', 'en': 'en'}
            def publish(self, *args, **kwargs):
                raise TimeoutError('Unknown outcome')
        sent, failures = publish_pending(self.store, self.config, Translator(), Telegram(), TODAY,
                                        lambda _: None, time.monotonic() + 30)
        self.assertEqual((sent, failures), (0, 1))
        actual_day = datetime.now(ZoneInfo(self.config['timezone'])).date()
        self.assertEqual(self.store.quota_used(actual_day, HASHES['ru']), 1)
        self.assertEqual(self.store.quota_used(actual_day, HASHES['en']), 0)

    def test_uncertain_send_blocks_later_runs_and_duplicate_listings(self):
        self.pending([event()])
        class Translator:
            def translate(self, event, language):
                return {'title': event.title, 'summary': 'Jazz concert'}
        class Telegram:
            channels = {'ru': 'ru'}
            calls = 0
            def publish(self, *args, **kwargs):
                self.calls += 1
                raise TimeoutError('Accepted message; response lost')
        telegram = Telegram()
        publish_pending(self.store, self.config, Translator(), telegram, TODAY, lambda _: None, time.monotonic() + 30)
        self.store.close()
        self.store = Store(self.path)
        self.pending([event(description='Changed source description'),
                      event(2, title=event().title, end='2026-10-20T22:00:00+03:00')])
        result = publish_pending(self.store, self.config, Translator(), telegram, TODAY + timedelta(days=1),
                                 lambda _: None, time.monotonic() + 30)
        self.assertEqual(result, (0, 0))
        self.assertEqual(telegram.calls, 1)
        self.assertEqual(self.store.delivery_holds(HASHES)[0]['source_key'], 'tampere:1')
        self.config['selection']['enabled'] = False
        # Disable the duplicate listing, then ensure the original still cannot resend.
        self.store.reconcile_selection('tampere', [event()], TODAY, next_month(TODAY))
        publish_pending(self.store, self.config, Translator(), telegram, TODAY, lambda _: None, time.monotonic() + 30)
        self.assertEqual(telegram.calls, 1)

    def test_legacy_reservation_requires_explicit_resolution(self):
        pending = self.pending([event()])
        event_id = pending[0][0]
        self.store.reserve_post(TODAY, HASHES['ru'], event_id, 5)
        self.assertEqual(self.store.pending(TODAY, ['ru', 'en'], HASHES)[0][2], ['en'])
        self.store.resolve_delivery(event().source_key, 'ru', HASHES['ru'])
        self.assertEqual(self.store.pending(TODAY, ['ru', 'en'], HASHES)[0][2], ['ru', 'en'])
        self.assertEqual(self.store.quota_used(TODAY, HASHES['ru']), 0)

    def test_delivery_resolution_command_does_not_send(self):
        from happeninki.resolve_delivery import main
        pending = self.pending([event()])
        event_id = pending[0][0]
        self.store.set_delivery(event_id, 'ru', HASHES['ru'], 'unknown', pending[0][1].fingerprint)
        with patch('sys.argv', ['resolve_delivery', 'tampere:1', '--language', 'ru', '--database', str(self.path), '--retry']), \
                patch.dict('os.environ', {'TELEGRAM_CHANNEL_RU': 'ru'}), patch('builtins.print'):
            main()
        self.assertEqual(self.store.delivery_status(event_id, 'ru', HASHES['ru']), 'pending')

    def test_resolving_existing_message_preserves_attempt_fingerprint(self):
        pending = self.pending([event()])
        event_id, original, _ = pending[0]
        self.store.set_delivery(event_id, 'ru', HASHES['ru'], 'unknown', original.fingerprint)
        self.store.reserve_post(TODAY, HASHES['ru'], event_id, 5)
        self.pending([event(description='Source changed while delivery held')])
        self.store.resolve_delivery(original.source_key, 'ru', HASHES['ru'], 123, 'photo')
        receipt = self.store.publication(event_id, 'ru', HASHES['ru'])
        self.assertEqual(receipt['fingerprint'], original.fingerprint)
        self.assertEqual(receipt['message_kind'], 'photo')
        self.assertEqual(self.store.quota_used(TODAY, HASHES['ru']), 1)
        self.assertEqual(self.store.pending(TODAY, ['ru'], HASHES)[0][2], ['ru'])
        with self.assertRaises(ValueError):
            self.store.resolve_delivery(original.source_key, 'ru', HASHES['ru'])

    def test_lost_receipt_checkpoint_restores_hold_not_resend(self):
        pending = self.pending([event()])
        event_id = pending[0][0]
        backup = Path(self.directory.name) / 'remote.db'
        class Translator:
            def translate(self, event, language):
                return {'title': event.title, 'summary': 'Jazz concert'}
        class Telegram:
            channels = {'ru': 'ru'}
            calls = 0
            def publish(self, *args, **kwargs):
                self.calls += 1
                return 123
        telegram = Telegram()
        def checkpoint(store):
            if store.publication(event_id, 'ru', HASHES['ru']):
                raise RuntimeError('Receipt upload failed')
            store.snapshot(backup)
        with self.assertRaisesRegex(RuntimeError, 'Receipt upload failed'):
            publish_pending(self.store, self.config, Translator(), telegram, TODAY, checkpoint, time.monotonic() + 30)
        self.store.close()
        self.path = backup
        self.store = Store(backup)
        publish_pending(self.store, self.config, Translator(), telegram, TODAY, lambda _: None, time.monotonic() + 30)
        self.assertEqual(telegram.calls, 1)

    def test_quota_survives_restart_reset_and_unknown_send(self):
        slot = self.store.reserve_post(TODAY, HASHES['ru'], 'one', 1)
        self.assertIsNotNone(slot)
        self.assertIsNone(self.store.reserve_post(TODAY, HASHES['ru'], 'two', 1))
        self.assertIsNotNone(self.store.reserve_post(TODAY, HASHES['en'], 'two', 1))
        self.store.close()
        self.store = Store(self.path)
        self.store.reset()
        self.assertEqual(self.store.quota_used(TODAY, HASHES['ru']), 1)
        self.assertIsNotNone(self.store.reserve_post(TODAY + timedelta(days=1), HASHES['ru'], 'two', 1))
        self.store.finish_reservation(slot, 'released')
        self.assertEqual(self.store.quota_used(TODAY, HASHES['ru']), 0)

    def test_publish_cap_repeated_runs_and_edits(self):
        self.pending([event(i) for i in range(7)])
        class Translator:
            def translate(self, event, language):
                return {'title': event.title, 'summary': 'Jazz concert'}
        class Telegram:
            channels = {'ru': 'ru', 'en': 'en'}
            calls = []
            def publish(self, language, message, message_id=None, **kwargs):
                self.calls.append((language, message_id))
                return len(self.calls)
        telegram = Telegram()
        for _ in range(2):
            publish_pending(self.store, self.config, Translator(), telegram, TODAY, lambda _: None, time.monotonic() + 30)
        self.assertEqual(len(telegram.calls), 10)
        self.assertEqual(sum(language == 'ru' for language, _ in telegram.calls), 5)
        self.store.ingest([event(0, description='Updated jazz concert')], TODAY, next_month(TODAY))
        publish_pending(self.store, self.config, Translator(), telegram, TODAY, lambda _: None, time.monotonic() + 30)
        self.assertEqual(len(telegram.calls), 12)
        self.assertTrue(all(message_id for _, message_id in telegram.calls[-2:]))

    def test_model_quotes_validation_cache_and_shadow_comparison(self):
        source = {'title': 'Children concert', 'description': 'Performed in Finnish'}
        facts = {'audience': {'value': 'children', 'field': 'title', 'quote': 'Children'},
                 'format': {'value': 'concert', 'field': 'title', 'quote': 'concert'},
                 'performance_language': {'value': 'fi', 'field': 'description', 'quote': 'Finnish'}}
        self.assertEqual(validate(json.dumps(facts), source), facts)
        self.assertIn('reject', comparison(facts, self.config))
        facts['audience']['quote'] = 'fabricated'
        with self.assertRaises(ValueError):
            validate(json.dumps(facts), source)
        facts = {name: {'value': 'unknown', 'field': '', 'quote': ''} for name in facts}
        class HTTP:
            calls = 0
            def request(self, *args, **kwargs):
                self.calls += 1
                return {'message': {'content': json.dumps(facts)}}
        http = HTTP()
        classifier = Classifier(http, self.config['ollama'], 'test-key')
        classifier.classify(event(), self.store)
        classifier.classify(event(), self.store)
        self.assertEqual(http.calls, 1)
        classifier.classify(event(description='changed'), self.store)
        self.assertEqual(http.calls, 2)


if __name__ == '__main__':
    unittest.main()
