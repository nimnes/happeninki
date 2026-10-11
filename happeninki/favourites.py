"""Register public event metadata; personal favourites never enter release state."""
import hashlib
import os
import re
from urllib.parse import urlsplit


class Favourites:
    def __init__(self, http, url, secret, username):
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc or parts.username or parts.query or parts.fragment or parts.path not in {'', '/'}:
            raise ValueError('FAVOURITES_WORKER_URL must be an HTTPS origin')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username) or not username.lower().endswith('bot'):
            raise ValueError('TELEGRAM_BOT_USERNAME must be the bot username without @')
        self.http, self.url, self.secret, self.username = http, url.rstrip('/'), secret, username

    @classmethod
    def from_environment(cls, http):
        values = [os.getenv(key, '').strip() for key in ('FAVOURITES_WORKER_URL', 'FAVOURITES_SYNC_SECRET', 'TELEGRAM_BOT_USERNAME')]
        if not any(values):
            return None
        if not all(values):
            raise ValueError('Configure all three favourites environment variables, or leave all empty')
        return cls(http, *values)

    def prepare(self, event, translation, language):
        event_id = hashlib.sha256(event.source_key.encode()).hexdigest()[:32]
        payload = {'id': event_id, 'language': language, 'title': translation['title'][:200],
                   'summary': translation['summary'][:500], 'url': event.url,
                   'venue': event.venue[:200], 'municipality': event.municipality[:100],
                   'start': event.start, 'end': event.end, 'dates': event.dates,
                   'date_only': event.date_only, 'cancelled': event.cancelled}
        result = self.http.request(self.url + '/events', method='POST', body=payload,
            headers={'Authorization': 'Bearer ' + self.secret}, service='Favourites', timeout=15)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise RuntimeError('Favourites did not confirm event registration')
        if event.cancelled:
            return {'inline_keyboard': []}
        label = '⭐ Save event' if language == 'en' else '⭐ Сохранить событие'
        return {'inline_keyboard': [[{'text': label,
            'url': f'https://t.me/{self.username}?start=save_{language}_{event_id}'}]]}
