import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from happeninki.__main__ import run
from happeninki.schedule import main, remaining_active_seconds


class ScheduleTests(unittest.TestCase):
    def test_daytime_boundaries(self):
        cases = [('07:59:59', 0), ('08:00:00', 14 * 3600),
                 ('18:00:00', 4 * 3600), ('21:59:59', 1), ('22:00:00', 0), ('23:00:00', 0)]
        for clock, expected in cases:
            with self.subTest(clock=clock):
                now = datetime.fromisoformat(f'2026-10-11T{clock}+03:00')
                self.assertEqual(remaining_active_seconds(now), expected)

    def test_utc_inputs_follow_helsinki_summer_and_winter_time(self):
        for date, opening in [('2026-07-01', 5), ('2026-12-01', 6)]:
            with self.subTest(date=date):
                before = datetime.fromisoformat(f'{date}T{opening-1:02d}:59:59+00:00')
                start = datetime.fromisoformat(f'{date}T{opening:02d}:00:00+00:00')
                self.assertEqual(remaining_active_seconds(before), 0)
                self.assertEqual(remaining_active_seconds(start), 14 * 3600)

    def test_nighttime_bot_run_skips_sources_credentials_and_state(self):
        args = SimpleNamespace(config='config.toml', mode='publish', daytime_only=True)
        with patch('happeninki.__main__.datetime') as clock, \
                patch('happeninki.__main__.collect') as collect, \
                patch('happeninki.__main__.ReleaseState') as remote, \
                patch('happeninki.__main__.Telegram') as telegram:
            clock.now.return_value = datetime.fromisoformat('2026-10-11T22:00:00+03:00')
            self.assertEqual(run(args), 0)
            collect.assert_not_called()
            remote.assert_not_called()
            telegram.assert_not_called()

    def test_gate_writes_github_output_for_both_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            for remaining, allowed in [(0, 'false'), (1, 'true')]:
                with patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}), \
                        patch('happeninki.schedule.remaining_active_seconds', return_value=remaining), \
                        patch('builtins.print'):
                    main()
                self.assertEqual(output.read_text().splitlines()[-1], f'allowed={allowed}')

    def test_work_deadline_is_cut_off_at_closing_time(self):
        args = SimpleNamespace(config='config.toml', mode='preview', release_state=True, daytime_only=True)
        with patch('happeninki.__main__.datetime') as clock, \
                patch('happeninki.__main__.HttpClient') as clients, \
                patch('happeninki.__main__.time.monotonic', return_value=100), \
                patch('happeninki.__main__.ReleaseState', side_effect=RuntimeError('stop before networking')):
            clock.now.return_value = datetime.fromisoformat('2026-10-11T21:59:59+03:00')
            with self.assertRaisesRegex(RuntimeError, 'stop before networking'):
                run(args)
            self.assertEqual(clients.return_value.deadline, 101)
