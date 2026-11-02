import os
import re
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo


def load_config(path="config.toml"):
    with Path(path).open("rb") as stream:
        config = tomllib.load(stream)
    ZoneInfo(config["timezone"])
    if set(config["languages"]) != {"ru", "en"}:
        raise ValueError("Configure exactly the ru and en languages.")
    if len(config["municipalities"]) != len(set(config["municipalities"])):
        raise ValueError("Municipalities must be unique.")
    for name in config["categories"]:
        if name not in config["category_mapping"]:
            raise ValueError(f"Unknown category: {name}")
    for pattern in config["exclude_title_patterns"]:
        re.compile(pattern)
    filters = config.get("filters", {})
    for key in ("exclude_children", "exclude_pensioners", "exclude_reading", "exclude_courses", "allow_finnish_learning",
                "exclude_workshops", "exclude_games", "exclude_standup", "exclude_lectures", "exclude_artist_meetings", "exclude_nightclubs", "allow_church_music"):
        if key in filters and not isinstance(filters[key], bool):
            raise ValueError(f"filters.{key} must be true or false")
    for key in ("travel_performance_cities", "travel_concert_venues", "excluded_source_categories", "excluded_source_keys", "exclude_title_keywords", "nightclub_venues", "music_venues", "music_artists", "international_music_artists", "finnish_music_artists", "church_choir_works"):
        values = filters.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"filters.{key} must be a list of nonempty strings")
    if filters.get("music_selection", "all") not in {"all", "curated"}:
        raise ValueError('filters.music_selection must be "all" or "curated"')
    if filters.get('church_choir_selection', 'all') not in {'all', 'notable'}:
        raise ValueError('filters.church_choir_selection must be all or notable')
    if any(':' not in work or any(not part.strip() for part in work.split(':', 1))
           for work in filters.get('church_choir_works', [])):
        raise ValueError('filters.church_choir_works entries must be Composer: Work')
    theatre_languages = filters.get("theatre_languages", [])
    if not isinstance(theatre_languages, list) or any(language not in {"en", "ru"} for language in theatre_languages):
        raise ValueError('filters.theatre_languages must contain only "en" or "ru", or be empty')
    art_master = config["sources"].get("art_master", {})
    if art_master.get("enabled"):
        for key in ("municipalities", "delivery_languages", "performance_languages"):
            values = art_master.get(key)
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"sources.art_master.{key} must be a list of nonempty strings")
        if not art_master["municipalities"] or not art_master["delivery_languages"]:
            raise ValueError("Art Master needs municipalities and delivery languages")
        for key in ("delivery_languages", "performance_languages"):
            if any(value not in {"ru", "en"} for value in art_master[key]):
                raise ValueError(f"sources.art_master.{key} only supports ru and en")
    for name in ('helsinki', 'turku'):
        settings = config['sources'].get(name, {})
        if not settings.get('enabled'):
            continue
        from .models import safe_url
        if not safe_url(settings.get('base_url')):
            raise ValueError(f'sources.{name}.base_url must be an HTTP(S) URL')
        if settings.get('municipalities') != [name.capitalize()]:
            raise ValueError(f'sources.{name}.municipalities must contain only {name.capitalize()}')
        if name == 'turku' and any(not isinstance(settings.get(key), str) or not settings[key].strip()
                                   for key in ('collection_id', 'area_id')):
            raise ValueError('Turku needs collection_id and area_id')
    for key in ("discovery_days", "max_events_per_run", "run_budget_seconds"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    if not 1 <= config["sources"]["tampere"]["window_days"] <= 60:
        raise ValueError("Tampere window_days must be between 1 and 60.")
    if os.getenv("OLLAMA_MODEL"):
        config["ollama"]["model"] = os.environ["OLLAMA_MODEL"]
    provider = os.getenv("LLM_PROVIDER", config.get("llm", {}).get("provider", "google")).lower().strip()
    if provider not in {"google", "ollama"}:
        raise ValueError("LLM_PROVIDER must be google or ollama")
    settings = dict(config[provider])
    settings["provider"] = provider
    for name in ("model", "url"):
        settings[name] = os.getenv(f"{provider.upper()}_{name.upper()}") or settings[name]
    config["llm"] = settings
    selection = config.setdefault('selection', {})
    if not isinstance(selection, dict):
        raise ValueError('selection must be a table')
    for key, value in {'enabled': False, 'daily_limit': 7, 'lead_days': 30,
                       'reconsider_days': 3, 'classifier_mode': 'off', 'classification_budget': 5,
                       'minimum_score': 0}.items():
        selection.setdefault(key, value)
    if not isinstance(selection.get('enabled', False), bool):
        raise ValueError('selection.enabled must be true or false')
    if selection.get('classifier_mode', 'off') not in {'off', 'shadow'}:
        raise ValueError('selection.classifier_mode must be off or shadow')
    if (not isinstance(selection['minimum_score'], int) or isinstance(selection['minimum_score'], bool)
            or selection['minimum_score'] < 0):
        raise ValueError('selection.minimum_score must be a nonnegative integer')
    bonus = selection.setdefault('tampere_priority_bonus', 10)
    if not isinstance(bonus, int) or isinstance(bonus, bool) or bonus < 0:
        raise ValueError('selection.tampere_priority_bonus must be a nonnegative integer')
    for key in ('daily_limit', 'lead_days', 'reconsider_days', 'classification_budget'):
        value = selection.get(key, 1)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f'selection.{key} must be a positive integer')
    digest = config.setdefault('digest', {})
    if not isinstance(digest, dict):
        raise ValueError('digest must be a table')
    digest.setdefault('enabled', False)
    digest.setdefault('max_events', 10)
    if not isinstance(digest['enabled'], bool):
        raise ValueError('digest.enabled must be true or false')
    if not isinstance(digest['max_events'], int) or isinstance(digest['max_events'], bool) or not 1 <= digest['max_events'] <= 10:
        raise ValueError('digest.max_events must be between 1 and 10')
    return config

