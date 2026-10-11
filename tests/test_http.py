import unittest
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from happeninki.http import HttpClient, RemoteError, RequestDeadlineExceeded


class HttpDeadlineTests(unittest.TestCase):
    def opener(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
        return opener

    def test_expired_deadline_starts_no_network_request(self):
        with patch('happeninki.http.time.monotonic', return_value=10), \
                patch('happeninki.http.build_opener') as build:
            with self.assertRaises(RequestDeadlineExceeded):
                HttpClient(deadline=10).request('https://example.com')
            build.assert_not_called()

    def test_timeout_is_bounded_by_remaining_budget(self):
        opener = self.opener()
        with patch('happeninki.http.time.monotonic', return_value=10), \
                patch('happeninki.http.build_opener', return_value=opener):
            self.assertEqual(HttpClient(deadline=12).request('https://example.com', timeout=90), {'ok': True})
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 2)

    def test_retries_recalculate_remaining_time(self):
        opener = self.opener()
        response = opener.open.return_value
        opener.open.side_effect = [URLError('timeout'), response]
        clock = [0]
        def pause(delay):
            clock[0] += delay
        with patch('happeninki.http.time.monotonic', side_effect=lambda: clock[0]), \
                patch('happeninki.http.time.sleep', side_effect=pause), \
                patch('happeninki.http.build_opener', return_value=opener):
            self.assertEqual(HttpClient(deadline=3).request('https://example.com'), {'ok': True})
        self.assertEqual([call.kwargs['timeout'] for call in opener.open.call_args_list], [3, 2])

    def test_retry_delay_cannot_exhaust_remaining_budget(self):
        opener = self.opener()
        opener.open.side_effect = URLError('timeout')
        with patch('happeninki.http.time.monotonic', return_value=0), \
                patch('happeninki.http.time.sleep') as sleep, \
                patch('happeninki.http.build_opener', return_value=opener):
            with self.assertRaises(RequestDeadlineExceeded):
                HttpClient(deadline=0.5).request('https://example.com')
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_timeout_after_attempted_send_stays_ambiguous(self):
        opener = self.opener()
        opener.open.side_effect = URLError('timeout')
        with patch('happeninki.http.time.monotonic', return_value=0), \
                patch('happeninki.http.build_opener', return_value=opener):
            with self.assertRaises(RemoteError):
                HttpClient(deadline=1).request('https://example.com', method='POST', retry=False)

