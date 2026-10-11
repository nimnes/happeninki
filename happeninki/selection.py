"""Explainable editorial selection, independent of Telegram delivery receipts."""
import hashlib
import json
import re
from datetime import date, datetime

from .filters import event_exclusion_reason, church_music_eligible, venue_matches, has_allowed_theatre_language, notable_church_choir, programme_text
from .models import normalized, plain_text


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


def performance_languages(event):
    """Use explicit performance evidence, never the listing's written language."""
    languages = set(event.performance_languages)
    title, description = plain_text(event.title), plain_text(event.description)
    description = '. '.join(sentence for sentence in re.split(r'[.!?]', description)
                            if not re.search(r'\b(?:previously|aiemmin)\b', sentence, re.I))
    text = title + '. ' + description
    for language, names in {'en': ('english', 'englanniksi'), 'ru': ('russian', 'venäjäksi'),
                            'fi': ('finnish', 'suomeksi')}.items():
        if language != 'fi' and has_allowed_theatre_language(title, description, [language]):
            languages.add(language)
        adjective = {'en': 'englanninkielinen', 'ru': 'venäjänkielinen', 'fi': 'suomenkielinen'}[language]
        patterns = (r'\b(?:performance language|event language|language of performance)\s*:\s*' + names[0] + r'\b',
                    r'\b(?:performed|sung|spoken|presented)\s+in\s+' + names[0] + r'\b',
                    r'\b(?:esitetään|lauletaan|esityskieli\s*(?:on|:)?)\s+' + names[1] + r'\b',
                    r'\b' + adjective + r'\s+(?:esitys|konsertti|näytelmä)\b',
                    r'\b' + names[0] + r'[- ]language\s+(?:performance|concert|show)\b')
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                context = text[max(0, match.start() - 30):match.start()]
                if not re.search(r'\b(?:not|never|ei|previously|aiemmin)\b', context, re.I):
                    languages.add(language)
    if re.search(r'\besityskieli\s*(?:on|:)?\s*suomi\b', text, re.I) and not re.search(
            r'\besityskieli\s+ei\s+ole\s+suomi\b', text, re.I):
        languages.add('fi')
    return languages


def score_event(event, config, today, now=None):
    preferences = config.get('filters', {})
    church = church_music_eligible(event.title, event.description, event.source_categories, event.address or event.venue, config)
    artist = any(
        re.search(r'(?<!\w)' + re.escape(artist) + r'(?!\w)', event.title, re.I)
        for artist in preferences.get('music_artists', []))
    preferred = event.category == 'music' and ((church and preferences.get('allow_church_music')) or artist)
    venue = event.category == 'music' and venue_matches(event.address or event.venue, preferences.get('music_venues', []))
    languages = performance_languages(event)
    major = event.category == 'music' and (venue_matches(event.address or event.venue,
        config.get('selection', {}).get('major_music_venues', [])) or
        artist or (church and notable_church_choir(event.title, event.description, config)))
    language_fit = 20 if languages.intersection({'en', 'ru'}) else (
        -20 if 'fi' in languages and event.category in {'music', 'culture'} and not major else 0)
    accessible_programme = re.search(
        r'\b(?:\w*jazz\w*|klassinen|klassisen|klassista|classical|barokki\w*|baroque|'
        r'kamarimusi\w*|chamber\s+music|джаз\w*|классическ\w*)\b',
        programme_text(event.title, event.description) + ' ' + ' '.join(event.source_categories), re.I)
    venue_only = event.category == 'music' and not (preferred or major or accessible_programme)
    components = {'preference_fit': 40 if preferred else 30 if event.category in {'music', 'festivals'} else 25,
                  'programme_context': 10 if preferred or venue else 0,
                  'language_accessibility': language_fit,
                  'music_interest': -15 if venue_only else 0,
                  'editorial_interest': 10 if event.category in {'exhibitions', 'language_learning'} or event.source == 'syo' else 0,
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
        elif score < config['selection'].get('minimum_score', 0) and not delivery_selected:
            status, reason = 'rejected', 'below minimum interest score'
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
