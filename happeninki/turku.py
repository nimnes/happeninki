"""Russian-language events from Turku's current public Townbase calendar."""
import re
from datetime import timedelta
from urllib.parse import urlencode

from .filters import event_exclusion_reason
from .models import Event
from .selection import performance_languages


def parse_turku(page, config):
    from .sources import parse_tampere
    # The listing's inLanguage/languages fields describe its translations only.
    probe = Event(source='turku', source_id='', title=page.get('name', ''),
                  description=page.get('descriptionLong') or page.get('descriptionShort', ''),
                  url='', municipality='Turku', venue='', address='', category='culture', start='', end='', dates=[])
    languages = performance_languages(probe)
    if 'ru' not in languages:
        return None
    page = dict(page, globalContentCategories=[tag.casefold() for tag in page.get('globalContentCategories', [])])
    parsing_config = dict(config, filters=dict(config.get('filters', {}),
                         music_venues=config['filters'].get('travel_concert_venues', [])))
    event = parse_tampere(page, 'Turku', parsing_config, source='turku',
                          performance_languages=languages, delivery_languages=['ru'])
    if event:
        # Area filtering is supplied by the calendar; reject an explicitly different city.
        if event.address and not re.search(r'\b(?:Turku|Åbo)\b', event.address, re.I):
            return None
        if event.source_key not in config.get('_published_source_keys', ()) and event_exclusion_reason(event, config):
            return None
    return event


class TurkuSource:
    name = 'turku'

    def __init__(self, config, http):
        self.config, self.http = config, http

    def fetch(self, start, end):
        settings = self.config['sources'][self.name]
        result, windows = {}, [(start, end)]
        while windows:
            beginning, finish = windows.pop()
            query = urlencode({'lang': 'fi', 'country': 'FI', 'mode': 'event',
                               'area_id': settings['area_id'], 'start': beginning.isoformat(),
                               'end': finish.isoformat(), 'sort': 'startDate'})
            url = f"{settings['base_url']}/api/collection/{settings['collection_id']}/content?{query}"
            data = self.http.request(url, service='Turku calendar')
            if not isinstance(data, dict) or not isinstance(data.get('pages'), list):
                raise ValueError('Turku calendar response schema changed')
            # The calendar caps responses at 500. Split date windows rather than
            # silently ignoring events beyond the cap.
            if len(data['pages']) >= 500 or data.get('hasMore') or data.get('next'):
                if beginning == finish:
                    raise ValueError('Turku daily result limit exceeded')
                middle = beginning + (finish - beginning) // 2
                windows.extend([(beginning, middle), (middle + timedelta(days=1), finish)])
                continue
            for page in data['pages']:
                event = parse_turku(page, self.config)
                if event and event.overlaps(start, end):
                    previous = result.get(event.source_key)
                    if previous and not event.date_only:
                        merged = {d['start']: d for d in previous.dates + event.dates}
                        event.dates = sorted(merged.values(), key=lambda d: d['start'])
                        event.start = event.dates[0]['start']
                        event.end = max(d['end'] for d in event.dates)
                    result[event.source_key] = event
        return list(result.values())
