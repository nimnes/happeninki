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
    for key in ("discovery_days", "max_events_per_run", "run_budget_seconds"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    if not 1 <= config["sources"]["tampere"]["window_days"] <= 60:
        raise ValueError("Tampere window_days must be between 1 and 60.")
    if os.getenv("OLLAMA_MODEL"):
        config["ollama"]["model"] = os.environ["OLLAMA_MODEL"]
    return config
