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
                "exclude_workshops", "exclude_games"):
        if key in filters and not isinstance(filters[key], bool):
            raise ValueError(f"filters.{key} must be true or false")
    for key in ("excluded_source_categories", "exclude_title_keywords"):
        values = filters.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"filters.{key} must be a list of nonempty strings")
    theatre_languages = filters.get("theatre_languages", [])
    if not isinstance(theatre_languages, list) or any(language not in {"en", "ru"} for language in theatre_languages):
        raise ValueError('filters.theatre_languages must contain only "en" or "ru", or be empty')
    for key in ("discovery_days", "max_events_per_run", "run_budget_seconds"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    if not 1 <= config["sources"]["tampere"]["window_days"] <= 60:
        raise ValueError("Tampere window_days must be between 1 and 60.")
    if os.getenv("OLLAMA_MODEL"):
        config["ollama"]["model"] = os.environ["OLLAMA_MODEL"]
    return config
