"""One ranked, source-linked next-week message per language channel."""
import html
import logging
import time
from dataclasses import asdict, replace
from datetime import date, timedelta

from .filters import event_exclusion_reason
from .http import RemoteError
from .models import safe_url
from .selection import performance_key, score_event
from .telegram import TelegramThrottled, channel_hash, date_range_label
from .translator import TranslationUnavailable

LOG = logging.getLogger(__name__)


def next_week(today):
    start = today + timedelta(days=7 - today.weekday())
    return start, start + timedelta(days=6)


def weekly_event(event, start, end):
    """Project occurrences into the week without changing stored event history."""
    if not event.overlaps(start, end):
        return None
    if event.dates:
        dates = [dict(item) for item in event.dates
                 if date.fromisoformat(item['start'][:10]) <= end and date.fromisoformat(item['end'][:10]) >= start]
        return replace(event, dates=dates, start=dates[0]['start'], end=max(item['end'] for item in dates))
    if event.date_only:
        return replace(event, start=max(event.start[:10], start.isoformat()), end=min(event.end[:10], end.isoformat()))
    return event


def shortlist(events, config, today, language):
    start, end = next_week(today)
    candidates = []
    for event in events:
        if (not config['sources'].get(event.source, {}).get('enabled', False)
                or event.cancelled or not safe_url(event.url) or event_exclusion_reason(event, config)
                or (event.delivery_languages and language not in event.delivery_languages)):
            continue
        projected = weekly_event(event, start, end)
        if projected:
            score, _ = score_event(projected, config, start)
            candidates.append((score, projected))
    candidates.sort(key=lambda item: (-item[0], item[1].next_occurrence(start), item[1].source_key))
    seen, selected = set(), []
    for score, event in candidates:
        identity = performance_key(event)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append((event, score))
        if len(selected) >= config['digest']['max_events']:
            break
    return selected


def shortened(text, limit):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def build_digest(entries, language, start, end):
    heading = {'en': 'Next week', 'ru': 'На следующей неделе'}[language]
    header = f'📅 <b>{heading} · {start:%d.%m.%Y}–{end:%d.%m.%Y}</b>'
    # Keep one Telegram message. Shorten individual descriptions first, then omit
    # the lowest-ranked entries if unusually long URLs still exceed the limit.
    count = len(entries)
    while count:
        for summary_limit, title_limit in ((160, 100), (100, 80), (60, 60)):
            blocks = [header]
            for index, (event, translation) in enumerate(entries[:count], 1):
                title = html.escape(shortened(translation['title'], title_limit))
                url = html.escape(safe_url(event.url), quote=True)
                occurrences = event.dates or [{'start': event.start, 'end': event.end}]
                dates = [date_range_label(item['start'], item['end'], start, event.date_only) for item in occurrences[:2]]
                if len(occurrences) > 2:
                    dates.append('…')
                location = shortened(', '.join(dict.fromkeys(filter(None, [event.venue, event.municipality]))), 70)
                details = ' · '.join(filter(None, ['; '.join(dates), location]))
                blocks.append(f'{index}. <b><a href="{url}">{title}</a></b>\n'
                              + html.escape(details) + '\n' + html.escape(shortened(translation['summary'], summary_limit)))
            message = '\n\n'.join(blocks)
            if len(message.encode('utf-16-le')) // 2 <= 4096:
                return message, count
        count -= 1
    return '', 0


def preview_digest(events, config, today, languages, store, translator=None):
    start, end = next_week(today)
    result = {'week_start': str(start), 'week_end': str(end), 'channels': {}}
    for language in languages:
        selected = shortlist(events, config, today, language)
        items = [{'event': asdict(event), 'score': score} for event, score in selected]
        channel = {'events': items}
        entries, untranslated = [], False
        for event, _ in selected:
            translation = store.translation(event, language)
            if translation is None:
                if translator:
                    translation = translator.translate(event, language)
                    store.cache_translation(event, language, translation)
                else:
                    translation = {'title': event.title, 'summary': event.description}
                    untranslated = True
            entries.append((event, translation))
        channel['message'], channel['included_events'] = build_digest(entries, language, start, end)
        channel['untranslated_source_fallback'] = untranslated
        result['channels'][language] = channel
    return result


def publish_digest(events, config, today, store, translator, telegram, checkpoint, deadline):
    start, end = next_week(today)
    sent, failures = 0, 0
    for language in config['languages']:
        if not telegram.channels.get(language):
            continue
        channel = channel_hash(telegram.channels[language])
        previous = store.weekly_digest(start, language, channel)
        if previous and previous['status'] in {'sent', 'unknown'}:
            if previous['status'] == 'unknown':
                LOG.warning('Weekly digest %s (%s) held after an uncertain send', start, language)
                failures += 1
            continue
        selected = shortlist(events, config, today, language)
        if not selected:
            continue  # Empty digests would add noise.
        entries = []
        try:
            for event, _ in selected:
                if time.monotonic() >= deadline:
                    LOG.warning('Weekly digest deferred: run budget reached')
                    checkpoint(store)
                    return sent, failures + 1
                translation = store.translation(event, language)
                if translation is None:
                    if time.monotonic() + 100 >= deadline:
                        checkpoint(store)
                        return sent, failures + 1
                    if translator is None:
                        raise TranslationUnavailable('Set OLLAMA_API_KEY to translate uncached digest entries')
                    translation = translator.translate(event, language)
                    store.cache_translation(event, language, translation)
                entries.append((event, translation))
            message, count = build_digest(entries, language, start, end)
            if not message:
                raise ValueError('Digest links cannot fit in a single Telegram message')
        except Exception as exc:
            LOG.error('Weekly digest preparation failed (%s): %s', language, type(exc).__name__)
            checkpoint(store)
            return sent, failures + 1
        if time.monotonic() >= deadline:
            checkpoint(store)
            return sent, failures + 1
        store.save_weekly_digest(start, language, channel, 'unknown', message)
        checkpoint(store)  # Hold before sending, including across lost receipt uploads.
        try:
            message_id = telegram.publish(language, message)
        except (TelegramThrottled, RemoteError) as exc:
            if isinstance(exc, TelegramThrottled) or exc.status in {400, 401, 403, 404}:
                store.save_weekly_digest(start, language, channel, 'pending', message)
            checkpoint(store)
            LOG.error('Weekly digest send failed (%s): %s', language, type(exc).__name__)
            return sent, failures + 1
        except Exception as exc:
            checkpoint(store)
            LOG.error('Weekly digest outcome unknown (%s): %s', language, type(exc).__name__)
            return sent, failures + 1
        store.save_weekly_digest(start, language, channel, 'sent', message, message_id)
        checkpoint(store)
        sent += 1
        LOG.info('Published weekly digest %s (%s): %d events', start, language, count)
    return sent, failures
