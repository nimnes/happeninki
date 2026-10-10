"""Explainable editorial selection, independent of Telegram delivery receipts."""
import hashlib
import json
import re
from datetime import date, datetime

from .filters import event_exclusion_reason, is_church_music, venue_matches
from .models import normalized


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def performance_key(event):
    # Same title, venue and occurrence; differing advertised end times are common.
    start = event.start
    if 'T' in start:
        start = datetime.fromisoformat(start).timestamp()
    occurrences = [datetime.fromisoformat(item['start']).timestamp() for item in event.dates]
    return digest([normalized(event.title), normalized(event.municipality), normalized(event.venue), start,
                   sorted(occurrences)])


def decision_key(event, config):
    return digest([event.fingerprint, config.get('filters', {}), config.get('selection', {}),
                   config['categories'], config['municipalities']])


def notice_date(event, today, now=None):
    upcoming = event.next_occurrence(today, now)
    return max(today, date.fromisoformat(upcoming[:10])) if upcoming else None


def score_event(event, config, today, now=None):
    preferences = config.get('filters', {})
    church = is_church_music(event.title, event.description, event.source_categories, event.address or event.venue)
    preferred = event.category == 'music' and ((church and preferences.get('allow_church_music')) or any(
        re.search(r'(?<!\w)' + re.escape(artist) + r'(?!\w)', event.title, re.I)
        for artist in preferences.get('music_artists', [])))
    venue = venue_matches(event.address or event.venue, preferences.get('music_venues', []))
    components = {'preference_fit': 40 if preferred else 30 if event.category in {'music', 'festivals'} else 25,
                  'programme_context': 10 if preferred or venue else 0,
                  'practical_information': 5 * bool(event.venue or event.address) + 5 * bool(event.url),
                  'timing': 10 if lead_in_window(event, config, today, now) else 0}
    # No invented audience, fame or external coverage points.
    return sum(components.values()), components


def rank_pending(store, pending, config, today, hashes, now=None):
    if not config.get('selection', {}).get('enabled', False):
        return [item for item in pending if not event_exclusion_reason(item[1], config)], {}
    decisions, candidates, updates = {}, [], []
    for event_id, event, languages in pending:
        existing = [lang for lang in languages if store.publication(event_id, lang, hashes[lang])]
        new = [lang for lang in languages if lang not in existing]
        if existing:
            updates.append((event_id, event, existing))
        score, components = score_event(event, config, today, now)
        reason = event_exclusion_reason(event, config)
        key = decision_key(event, config)
        record = store.editorial(event_id, key, today)
        if record['status'] == 'scheduled' and lead_in_window(event, config, today, now):
            with store.connection:
                store.connection.execute('UPDATE editorial SET first_considered=? WHERE event_id=? AND policy_key=?',
                                         (today.isoformat(), event_id, key))
            record = store.editorial(event_id, key, today)
        age = (today - date.fromisoformat(record['first_considered'])).days
        upcoming = notice_date(event, today, now)
        lead = (upcoming - today).days if upcoming else None
        delivery_selected = store.has_publication(event_id, hashes.values()) or any(
            store.delivery_status(event_id, language, hashes[language]) == 'pending' for language in new)
        status = 'candidate'
        if reason:
            status = 'rejected'
        elif lead is None:
            status, reason = 'skipped', 'no upcoming occurrence'
        elif lead > config['selection']['lead_days']:
            status, reason = 'scheduled', 'outside publication window'
        elif age >= config['selection']['reconsider_days'] and not delivery_selected:
            status, reason = 'skipped', 'reconsideration window expired'
        info = {'source_key': event.source_key, 'title': event.title, 'score': score, 'components': components, 'status': status, 'reason': reason,
                'online_interest': 'unknown', 'update_languages': existing}
        info['next_occurrence'] = event.next_occurrence(today, now)
        decisions[event_id] = info
        store.record_editorial(event_id, key, status, info)
        if new and status == 'candidate':
            candidates.append((event_id, event, new))
    candidates.sort(key=lambda item: (-decisions[item[0]]['score'], decisions[item[0]]['next_occurrence'], item[1].source_key))
    # Suppress duplicate listings conservatively, including already published ones.
    known = store.published_performances(hashes)
    seen = set(known)
    ranked = []
    for event_id, event, languages in candidates:
        available = []
        for language in languages:
            identity = (performance_key(event), hashes[language])
            if identity not in seen:
                available.append(language)
                seen.add(identity)
        if available:
            ranked.append((event_id, event, available))
        else:
            decisions[event_id].update(status='duplicate', reason='same performance already posted or ranked')
            store.record_editorial(event_id, decision_key(event, config), 'duplicate', decisions[event_id])
    return updates + ranked, decisions


def lead_in_window(event, config, today, now=None):
    upcoming = notice_date(event, today, now)
    return upcoming is not None and (upcoming - today).days <= config['selection']['lead_days']
