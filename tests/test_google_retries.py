import io
import json
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from happeninki.http import HttpClient, RemoteError, RequestDeadlineExceeded, google_retry_delay
from happeninki.config import load_config
from happeninki.translator import Translator, TranslationUnavailable
import test_translator


class GoogleRetryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = 0
        self.sleeps = []
        self.stack.enter_context(patch('happeninki.http.time.monotonic', side_effect=lambda: self.clock))
        self.stack.enter_context(patch('happeninki.http.random.uniform', return_value=0))
        self.stack.enter_context(patch('happeninki.http.time.sleep', side_effect=self.sleep))
        self.opener = MagicMock()
        self.success = self.opener.open.return_value
        self.success.__enter__.return_value.read.return_value = b'{"ok":true}'
        self.stack.enter_context(patch('happeninki.http.build_opener', return_value=self.opener))

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.clock += delay

    def error(self, status, headers=None, details=None):
        body = {"error": {"status": "INTERNAL", "message": "private-key source text",
                          "details": details or []}}
        return HTTPError('https://example.org/private-key', status, 'private-key',
                         headers or {}, io.BytesIO(json.dumps(body).encode()))

    def request(self, **kwargs):
        return HttpClient(**kwargs).request('https://example.org', service='google', timeout=90)

    def test_four_google_attempts_with_exponential_backoff(self):
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.sleeps.clear()
                self.opener.open.reset_mock()
                self.opener.open.side_effect = [self.error(status) for _ in range(3)] + [self.success]
                with self.assertLogs('happeninki.http', level='WARNING'):
                    self.assertEqual(self.request(), {'ok': True})
                self.assertEqual(self.opener.open.call_count, 4)
                self.assertEqual(self.sleeps, [5, 10, 20])
                self.assertTrue(all(call.kwargs['timeout'] <= 40 for call in self.opener.open.call_args_list))

    def test_exhaustion_is_temporary_and_logs_only_safe_status(self):
        self.opener.open.side_effect = [self.error(500) for _ in range(4)]
        with self.assertLogs('happeninki.http', level='WARNING') as logs:
            with self.assertRaises(RemoteError) as caught:
                self.request()
        self.assertTrue(caught.exception.transient)
        self.assertIn('INTERNAL', str(caught.exception))
        text = str(caught.exception) + str(logs.output)
        self.assertNotIn('private-key', text)
        self.assertNotIn('source text', text)
        self.assertEqual(self.opener.open.call_count, 4)

    def test_authentication_and_model_errors_are_not_temporary(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = self.error(status)
                with self.assertRaises(RemoteError) as caught:
                    self.request()
                self.assertFalse(caught.exception.transient)
                self.assertEqual(self.opener.open.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_google_retry_info_and_header_are_both_respected(self):
        self.opener.open.side_effect = [
            self.error(429, {'Retry-After': '15'}, [{
                '@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '25.5s'
            }]), self.success]
        with self.assertLogs('happeninki.http', level='WARNING'):
            self.request()
        self.assertEqual(self.sleeps, [25.5])

    def test_long_server_cooldown_is_deferred_without_retrying_early(self):
        self.opener.open.side_effect = self.error(429, {'Retry-After': '3600'})
        with self.assertRaises(RemoteError) as caught:
            self.request()
        self.assertTrue(caught.exception.transient)
        self.assertEqual(self.opener.open.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_network_failures_use_backoff_and_remain_temporary(self):
        self.opener.open.side_effect = URLError('private-key')
        with self.assertLogs('happeninki.http', level='WARNING') as logs:
            with self.assertRaises(RemoteError) as caught:
                self.request()
        self.assertTrue(caught.exception.transient)
        self.assertEqual(self.sleeps, [5, 10, 20])
        self.assertNotIn('private-key', str(logs.output) + str(caught.exception))

    def test_global_budget_stops_retry_and_bounds_timeout(self):
        self.opener.open.side_effect = self.error(500)
        with self.assertLogs('happeninki.http', level='WARNING'):
            with self.assertRaises(RequestDeadlineExceeded):
                self.request(deadline=4)
        self.assertEqual(self.opener.open.call_count, 1)
        self.assertEqual(self.opener.open.call_args.kwargs['timeout'], 4)
        self.assertEqual(self.sleeps, [])

    def test_operation_budget_cannot_be_extended_by_retries(self):
        def slow_failure(*args, **kwargs):
            self.clock += kwargs['timeout']
            raise self.error(500)
        self.opener.open.side_effect = slow_failure
        with self.assertLogs('happeninki.http', level='WARNING'):
            with self.assertRaises(RemoteError):
                self.request()
        self.assertLessEqual(self.clock, 180)
        self.assertEqual(self.opener.open.call_count, 4)

    def test_invalid_json_stays_an_unexpected_failure(self):
        self.success.__enter__.return_value.read.return_value = b'not JSON'
        with self.assertRaisesRegex(RuntimeError, 'invalid JSON response') as caught:
            self.request()
        self.assertNotIsInstance(caught.exception, RemoteError)
        self.assertEqual(self.opener.open.call_count, 1)

    def test_retry_after_http_date_and_malformed_values(self):
        class FixedDateTime:
            @staticmethod
            def now(tz):
                return datetime(2026, 11, 5, tzinfo=timezone.utc)
        header = format_datetime(datetime(2026, 11, 5, 0, 0, 30, tzinfo=timezone.utc))
        with patch('happeninki.http.datetime', FixedDateTime):
            self.assertEqual(google_retry_delay(header, {}, 0), 30)
        for value in ('invalid', '-1', 'nan', 'inf'):
            self.assertEqual(google_retry_delay(value, {}, 0), 5)

    def test_no_retry_option_still_makes_only_one_google_request(self):
        self.opener.open.side_effect = self.error(500)
        with self.assertRaises(RemoteError):
            HttpClient().request('https://example.org', service='google', retry=False)
        self.assertEqual(self.opener.open.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_google_changes_do_not_reclassify_telegram_errors(self):
        self.assertFalse(RemoteError('Telegram', 500).transient)
        self.assertFalse(RemoteError('Telegram').transient)
        self.assertFalse(RemoteError('Source', 429).transient)


class GoogleTranslationSeverityTests(unittest.TestCase):
    def setUp(self):
        fixture = test_translator.TranslationTests()
        fixture.setUp()
        self.event = fixture.event
        self.settings = load_config()['llm']
        self.settings['provider'] = 'google'

    def test_transient_google_errors_stop_translation_as_warnings(self):
        for status in (None, 408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                http = test_translator.Responses(RemoteError('google', status))
                with self.assertRaises(TranslationUnavailable) as caught:
                    Translator(http, self.settings, 'fake').translate(self.event, 'ru')
                self.assertTrue(caught.exception.transient)
                self.assertEqual(len(http.calls), 1)

    def test_google_access_errors_stay_fatal(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                http = test_translator.Responses(RemoteError('google', status))
                with self.assertRaises(TranslationUnavailable) as caught:
                    Translator(http, self.settings, 'fake').translate(self.event, 'ru')
                self.assertFalse(caught.exception.transient)
