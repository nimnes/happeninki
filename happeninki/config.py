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
    for key in ("exclude_children", "exclude_reading", "exclude_courses", "allow_finnish_learning",
                "exclude_workshops", "exclude_games", "exclude_standup", "exclude_lectures", "exclude_nightclubs", "allow_church_music"):
        if key in filters and not isinstance(filters[key], bool):
            raise ValueError(f"filters.{key} must be true or false")
    for key in ("excluded_source_categories", "exclude_title_keywords", "nightclub_venues", "music_venues", "music_artists"):
        values = filters.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"filters.{key} must be a list of nonempty strings")
    if filters.get("music_selection", "all") not in {"all", "curated"}:
        raise ValueError('filters.music_selection must be "all" or "curated"')
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
    for key in ("discovery_days", "max_events_per_run", "run_budget_seconds"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    if not 1 <= config["sources"]["tampere"]["window_days"] <= 60:
        raise ValueError("Tampere window_days must be between 1 and 60.")
    if os.getenv("OLLAMA_MODEL"):
        config["ollama"]["model"] = os.environ["OLLAMA_MODEL"]
    selection = config.setdefault('selection', {})
    if not isinstance(selection, dict):
        raise ValueError('selection must be a table')
    for key, value in {'enabled': False, 'daily_limit': 5, 'lead_days': 30,
                       'reconsider_days': 3, 'classifier_mode': 'off', 'classification_budget': 5}.items():
        selection.setdefault(key, value)
    if not isinstance(selection.get('enabled', False), bool):
        raise ValueError('selection.enabled must be true or false')
    if selection.get('classifier_mode', 'off') not in {'off', 'shadow'}:
        raise ValueError('selection.classifier_mode must be off or shadow')
    for key in ('daily_limit', 'lead_days', 'reconsider_days', 'classification_budget'):
        value = selection.get(key, 1)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f'selection.{key} must be a positive integer')
    return config
