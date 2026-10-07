"""Personal event preferences, applied before translation and publication."""
import re

from .models import plain_text

CHILDREN = re.compile(r"\b(lasten\w*|lapsille|lapsiperhe\w*|vauva\w*|taapero\w*|satutuokio\w*|children(?:'s)?|kids|toddlers?|babies)\b", re.I)
CHILD_AUDIENCE = re.compile(r"(?:suunnattu|tarkoitettu|sopii|suunniteltu)\s+(?:\w+\s+){0,3}(?:lapsille|lapsiperheille)|(?:for|aimed at)\s+(?:young\s+)?(?:children|kids|toddlers)", re.I)
READING = re.compile(r"\b(\w*lukukoira\w*|lue\s+koir(?:alle|ille)|lukupiir\w*|lukuhetk\w*|lukutuokio\w*|satutuokio\w*|kirjakerho\w*|book\s+club|reading\s+(?:group|club)|(?:read|reading)\s+to\s+(?:(?:a|the)\s+)?dogs?|story\s*time)\b", re.I)
COURSES = re.compile(r"\b(\w*kurss\w*|\w*oppitun\w*|courses?|classes?|lessons?|training\s+course)\b", re.I)
FINNISH_LEARNING = re.compile(r"\b(suomen\s+kiel\w*|suomea\s+(?:oppi\w*|opiskele\w*|harjoit\w*)|(?:puhutaan|puhu|opitaan|opiskellaan|harjoitellaan)\s+suomea|finnish\s+(?:language|courses?|classes?|lessons?|conversation)|(?:learn|learning|practice|practise)\s+finnish)\b", re.I)
LANGUAGE_ACTIVITY = re.compile(r"\b(\w*kurss\w*|\w*kielikahvila\w*|\w*keskusteluryhm\w*|\w*kieliryhm\w*|\w*opetus\w*|courses?|classes?|lessons?|language\s+caf[eé]|conversation\s+(?:group|club))\b", re.I)
FINNISH_PRACTICE = re.compile(r"\b(suomen\s+kielen\s+(?:kurss\w*|opetu\w*|oppimi\w*|opiskel\w*|harjoit\w*)|(?:puhutaan|puhu|opitaan|opiskellaan|harjoitellaan)\s+suomea|suomea\s+(?:oppi\w*|opiskele\w*|harjoit\w*)|finnish\s+(?:language\s+)?(?:courses?|classes?|lessons?|conversation)|(?:learn|learning|practice|practise)\s+finnish)\b", re.I)
WORKSHOPS = re.compile(r"\b(\w*työpaja\w*|\w*askartelu\w*|workshops?|craft\s+(?:group|session))\b", re.I)
GAMES = re.compile(r"\b(\w*bingo\w*|pub\s*quiz\w*|pubivisa\w*|tietovisa\w*|karaoke\w*)\b", re.I)


def is_finnish_learning(title, description):
    # A concert description mentioning Finnish songs is not a language class.
    return bool(FINNISH_PRACTICE.search(title) or
                (LANGUAGE_ACTIVITY.search(title) and FINNISH_LEARNING.search(title)) or
                (LANGUAGE_ACTIVITY.search(title) and FINNISH_PRACTICE.search(description)))


def exclusion_reason(title, description, source_categories, config):
    preferences = config.get("filters", {})
    title, description = plain_text(title), plain_text(description)
    tags = {tag.casefold() for tag in source_categories}
    if any(re.search(pattern, title) for pattern in config.get("exclude_title_patterns", [])):
        return "custom title pattern"
    if any(keyword.casefold() in title.casefold() for keyword in preferences.get("exclude_title_keywords", [])):
        return "custom title keyword"
    if tags.intersection(tag.casefold() for tag in preferences.get("excluded_source_categories", [])):
        return "custom source category"
    if preferences.get("exclude_children") and (
            "kids and family" in tags or CHILDREN.search(title) or CHILD_AUDIENCE.search(description)):
        return "children's activities"
    learning = preferences.get("allow_finnish_learning") and is_finnish_learning(title, description)
    if preferences.get("exclude_reading") and (
            READING.search(title) or ("literature" in tags and not learning)):
        return "reading activities"
    if preferences.get("exclude_courses") and COURSES.search(title) and not learning:
        return "courses"
    if preferences.get("exclude_workshops") and WORKSHOPS.search(title):
        return "workshops"
    if preferences.get("exclude_games") and GAMES.search(title):
        return "bingo, quizzes or karaoke"
    return None


def event_exclusion_reason(event, config):
    if event.municipality not in config["municipalities"] or event.category not in config["categories"]:
        return "area or category"
    return exclusion_reason(event.title, event.description, event.source_categories, config)
