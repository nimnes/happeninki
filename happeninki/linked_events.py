"""Russian-language events from Helsinki's public Linked Events calendar."""
from datetime import timedelta
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from .models import Event, plain_text, parse_datetime, safe_url
from .filters import event_exclusion_reason


def localized(value):
    if not isinstance(value, dict):
        return plain_text(value)
    return next((plain_text(value[key]) for key in ('ru', 'fi', 'en', 'sv') if value.get(key)), '')


def parse_linked_event(page, config):
    if page.get('deleted') or page.get('super_event_type') == 'recurring':
        return None  # Individual occurrences are returned separately.
    languages = [item.get('id') or item.get('@id', '').rstrip('/').rsplit('/', 1)[-1]
                 for item in page.get('in_language', [])]
    if 'ru' not in languages:
        return None
    location = page.get('location') or {}
    city = localized(location.get('address_locality'))
    helsinki = any(item.get('ocd_id') == 'ocd-division/country:fi/kunta:helsinki'
                   for item in location.get('divisions', []))
    if not helsinki and city.casefold() not in {'helsinki', 'хельсинки', 'helsingfors'}:
        return None
    title = localized(page.get('name'))
    if not title or not page.get('id') or not page.get('start_time'):
        raise ValueError('Linked Events listing missing title, ID or start')
    timezone = ZoneInfo(config['timezone'])
    start = parse_datetime(page['start_time'], timezone)
    end = parse_datetime(page.get('end_time') or page['start_time'], timezone)
    if end < start:
        raise ValueError('Linked Events occurrence ends before start')
    tags = []
    for item in page.get('keywords', []):
        names = item.get('name') or {}
        tags.extend(plain_text(name).casefold() for name in names.values() if name)
    if isinstance(page.get('audience_max_age'), int) and page['audience_max_age'] < 13:
        tags.append('kids and family')
    category = next((name for name in ('music', 'exhibitions', 'festivals', 'food', 'culture')
                     if set(tags).intersection(config['category_mapping'][name])), 'culture')
    offers = page.get('offers') or []
    url = safe_url(localized(page.get('info_url'))) or (
        'https://tapahtumat.hel.fi/fi/events/' + page['id'])
    images = page.get('images') or []
    event = Event(source='helsinki', source_id=page['id'], title=title,
                  description=localized(page.get('description') or page.get('short_description')),
                  url=url, municipality='Helsinki', venue=localized(location.get('name')),
                  address=localized(location.get('street_address')), category=category,
                  start=start.isoformat(), end=end.isoformat(),
                  dates=[{'start': start.isoformat(), 'end': end.isoformat()}],
                  date_only=page.get('has_start_time') is False,
                  cancelled=page.get('event_status') == 'EventCancelled',
                  price=('0 €' if offers[0].get('is_free') else localized(offers[0].get('price'))) if offers else '',
                  image_url=safe_url(images[0].get('url')) if images else '',
                  source_categories=tags, delivery_languages=['ru'], performance_languages=languages)
    return None if (event.source_key not in config.get('_published_source_keys', ())
                    and event_exclusion_reason(event, config)) else event


class HelsinkiSource:
    name = 'helsinki'

    def __init__(self, config, http):
        self.config, self.http = config, http

    def fetch(self, start, end):
        base = self.config['sources'][self.name]['base_url'].rstrip('/')
        query = urlencode({'start': start.isoformat(), 'end': (end + timedelta(days=1)).isoformat(),
                           'in_language': 'ru', 'include': 'location,keywords', 'page_size': 100})
        url, visited, result = base + '/event/?' + query, set(), {}
        while url:
            if url in visited or len(visited) >= 100 or urlsplit(url).netloc != urlsplit(base).netloc:
                raise ValueError('Unexpected Linked Events pagination')
            visited.add(url)
            data = self.http.request(url, service='Helsinki Linked Events')
            if not isinstance(data, dict) or not isinstance(data.get('data'), list) or not isinstance(data.get('meta'), dict):
                raise ValueError('Linked Events response schema changed')
            for page in data['data']:
                event = parse_linked_event(page, self.config)
                if event and event.overlaps(start, end):
                    result[event.source_key] = event
            url = data['meta'].get('next')
        return list(result.values())
