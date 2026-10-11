"""The publishing workflow's daytime window, including Helsinki daylight saving."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo('Europe/Helsinki')
START_HOUR = 8
END_HOUR = 22


def remaining_active_seconds(now=None):
    now = (now or datetime.now(HELSINKI)).astimezone(HELSINKI)
    if not START_HOUR <= now.hour < END_HOUR:
        return 0
    closing = now.replace(hour=END_HOUR, minute=0, second=0, microsecond=0)
    return closing.timestamp() - now.timestamp()


def main():
    allowed = remaining_active_seconds() > 0
    output = os.getenv('GITHUB_OUTPUT')
    if output:
        with Path(output).open('a', encoding='utf-8') as destination:
            destination.write(f'allowed={str(allowed).lower()}\n')
    print('Daytime window open (08:00–22:00 Helsinki).' if allowed
          else 'Nighttime: skipping work until a later daytime run.')


if __name__ == '__main__':
    main()
