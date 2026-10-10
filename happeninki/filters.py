"""Personal event preferences, applied before translation and publication."""
import re

from .models import plain_text, normalized

CHILDREN = re.compile(r"\b(lasten\w*|lapsille|lapsiperhe\w*|vauva\w*|taapero\w*|satutuokio\w*|children(?:'s)?|kids|toddlers?|babies)\b", re.I)
CHILD_AUDIENCE = re.compile(r"(?:suunnattu|tarkoitettu|sopii|suunniteltu)\s+(?:\w+\s+){0,3}(?:lapsille|lapsiperheille)|(?:for|aimed at)\s+(?:young\s+)?(?:children|kids|toddlers)", re.I)
CHILD_PROJECT = re.compile(
    r"\b(?:\w*perhepäivähoi\w*|\w*päiväkoti\w*|\w*päiväkode\w*|daycare|day\s+care|preschool|kindergarten)\b", re.I)
CHILD_PARTICIPATION = re.compile(
    r"\b(?:lapset\s+(?:kokevat|tekevät|luovat|osallistuvat)|lasten\s+(?:tekem\w*|taide\w*|töi\w*|projekt\w*)|"
    r"(?:created|made|produced)\s+by\s+(?:children|kids)|children(?:'s)?\s+(?:art|artwork|project)\w*)\b", re.I)
READING = re.compile(r"\b(\w*lukukoira\w*|lue\s+koir(?:alle|ille)|lukupiir\w*|lukuhetk\w*|lukutuokio\w*|satutuokio\w*|kirjakerho\w*|book\s+club|reading\s+(?:group|club)|(?:read|reading)\s+to\s+(?:(?:a|the)\s+)?dogs?|story\s*time)\b", re.I)
COURSES = re.compile(r"\b(\w*kurss\w*|\w*oppitun\w*|courses?|classes?|lessons?|training\s+course)\b", re.I)
FINNISH_LEARNING = re.compile(r"\b(suomen\s+kiel\w*|suomea\s+(?:oppi\w*|opiskele\w*|harjoit\w*)|(?:puhutaan|puhu|opitaan|opiskellaan|harjoitellaan)\s+suomea|finnish\s+(?:language|courses?|classes?|lessons?|conversation)|(?:learn|learning|practice|practise)\s+finnish)\b", re.I)
LANGUAGE_ACTIVITY = re.compile(r"\b(\w*kurss\w*|\w*kielikahvila\w*|\w*keskusteluryhm\w*|\w*kieliryhm\w*|\w*opetus\w*|courses?|classes?|lessons?|language\s+caf[eé]|conversation\s+(?:group|club))\b", re.I)
FINNISH_PRACTICE = re.compile(r"\b(suomen\s+kielen\s+(?:kurss\w*|opetu\w*|oppimi\w*|opiskel\w*|harjoit\w*)|(?:puhutaan|puhu|opitaan|opiskellaan|harjoitellaan)\s+suomea|suomea\s+(?:oppi\w*|opiskele\w*|harjoit\w*)|finnish\s+(?:language\s+)?(?:courses?|classes?|lessons?|conversation)|(?:learn|learning|practice|practise)\s+finnish)\b", re.I)
WORKSHOPS = re.compile(r"\b(\w*työpaja\w*|\w*askartelu\w*|workshops?|craft\s+(?:group|session))\b", re.I)
GAMES = re.compile(r"\b(\w*bingo\w*|pub\s*quiz\w*|pubivisa\w*|tietovisa\w*|karaoke\w*)\b", re.I)
CHILD_SHOW = re.compile(r"\b(?:koko\s+perhe(?:elle|en)|lasten\s+(?:konsertti\w*|esitys\w*|teatteri\w*|musikaali\w*)|"
                        r"(?:show|concert|performance)\s+for\s+(?:the\s+whole\s+family|children))\b", re.I)
THEATRE = re.compile(r"\b(\w*näytelmä\w*|teatteriesitys\w*|musikaali(?:n|a|ssa|sta|in|lla|lle|t|en|komedia\w*|esitys\w*)?|musical\s+(?:theatre|theater|comedy)|stage\s+play|theatr(?:e|ical)\s+(?:play|performance))\b", re.I)
# Check the whole listing for explicit event formats; source tags are often incomplete.
STANDUP = re.compile(r"\b(?:stand[ -]?up|standupkomi\w*|стендап\w*)\b", re.I)
LECTURES = re.compile(r"\b(?:\w*luento\w*|lectures?|лекци\w*)\b", re.I)
NIGHTCLUB = re.compile(r"\b(?:yökerho\w*|night\s*club\w*|club\s+night|klubi[ -]?ilta\w*|"
                       r"dj[ -]?(?:set|night|ilta)\w*|дискотек\w*|ночной\s+клуб)\b", re.I)
CHILD_AGE = re.compile(r"\b(?:suositusikä|ikä(?:suositus|raja)?|recommended\s+age|ages?)\s*[:]?\s*"
                       r"(?:yli\s+|over\s+)?([0-9]{1,2})(?:\s*[–-]\s*([0-9]{1,2}))?"
                       r"(?:\s*[- ]?vuotia\w*|\s*years?\w*|\s*\+)?", re.I)


CHURCH_VENUE = re.compile(
    r"\b(?:\w*kirkko|\w*kirkon|church|cathedral|chapel|kappeli|\w*kapell|kyrka|kyrkan)\b", re.I)
CHURCH_MUSIC = re.compile(
    r"\b(?:klassinen|klassisen|klassista|klassisesta|klassiseen|classical|barokki\w*|baroque|"
    r"kamarimusi\w*|chamber\s+music|urkumusi\w*|urku(?:konsert\w*|resitaali\w*)|organ\s+(?:music|recital|concert)|"
    r"\w*kuoro\w*|choirs?|choral|\w*jazz\w*|джаз\w*|хор|хоров\w*|классическ\w*)\b", re.I)
CHOIR = re.compile(r'\b(?:\w*kuoro\w*|choirs?|choral|хор|хоров\w*)\b', re.I)
CHOIR_PERFORMANCE = re.compile(
    r'\b(?:\w*kuoro\w*\s+(?:\w+\s+){0,4}(?:esittää|esittävät|esiintyy|esiintyvät|laulaa|laulavat)|'
    r'choir\s+(?:\w+\s+){0,3}(?:performs?|sings?|presents?)|choral\s+concert)\b', re.I)
PROGRAMME = re.compile(
    r'\b(?:ohjelmassa|konsertissa\s+kuullaan|esittää|esittävät|esitetään|'
    r'perform(?:s|ing)?|present(?:s|ing)?|programme|program|features?)\b', re.I)
LARGE_CHOIR_EVENT = re.compile(
    r'\b(?:sinfoniaorkesteri\w*|symphony\s+orchestra|mass(?:ed)?\s+choir|'
    r'(?:[3-9]|[1-9][0-9]+)\s+(?:kuoroa|choirs)|[1-9][0-9]{2,}\s+(?:laulajaa|singers)|'
    r'(?:kansainväli\w*|valtakunnalli\w*)\s+(?:\w+\s+){0,3}kuorofestivaali\w*|'
    r'(?:international|national)\s+(?:choral|choir)\s+festival)\b', re.I)


def programme_text(title, description):
    # Repertoire/scale must concern this concert, not an artist biography.
    parts = [plain_text(title)]
    description = plain_text(description)
    for match in PROGRAMME.finditer(description):
        snippet = description[match.start():match.start() + 350]
        snippet = re.split(r'[!?]|\.(?:\s+(?=[A-ZÄÖÅ])|$)', snippet, maxsplit=1)[0]
        context = description[max(0, match.start() - 80):match.start()] + snippet
        if not re.search(r'\b(?:aiemmin|previously|not|ei|vuonna\s+(?:19|20)[0-9]{2})\b', context, re.I):
            parts.append(snippet)
    return ' '.join(parts)


def notable_church_choir(title, description, config):
    programme = normalized(programme_text(title, description))
    for entry in config.get('filters', {}).get('church_choir_works', []):
        composer, work = (normalized(part) for part in entry.split(':', 1))
        composer_pattern = r'\b' + re.escape(composer) + r'(?:in|n)?\b'
        work_pattern = r'\b' + r'\s*'.join(re.escape(word) for word in work.split()) + r'\b'
        # A bare "Requiem" is insufficient: many composers wrote one. Other
        # configured titles identify the requested work without an attribution.
        if re.search(work_pattern, programme) and (work != 'requiem' or re.search(composer_pattern, programme)):
            return True
    return bool(LARGE_CHOIR_EVENT.search(programme_text(title, description)))


def is_church_choir(title, description, tags):
    return bool(CHOIR.search(title) or any(CHOIR.search(tag) for tag in tags)
                or CHOIR_PERFORMANCE.search(description)
                or any(CHOIR.search(sentence) and not re.search(
                    r'\b(?:aiemmin|previously|kuorossa|sang\s+in|member\s+of)\b', sentence, re.I)
                       for sentence in re.split(r'[.!?]', description)))


def church_music_eligible(title, description, tags, venue, config):
    church = CHURCH_VENUE.search(plain_text(venue).split(',', 1)[0])
    notable = church and notable_church_choir(title, description, config)
    choir = is_church_choir(title, description, tags)
    if choir and config.get('filters', {}).get('church_choir_selection') == 'notable' and not notable:
        return False
    return bool(is_church_music(title, description, tags, venue) or notable)


def is_church_music(title, description, tags, venue):
    # Match the venue name, not a street such as Kirkkokatu or a church mentioned
    # in an artist biography. Address fields conventionally start with the venue.
    name = plain_text(venue).split(",", 1)[0]
    return bool(CHURCH_VENUE.search(name) and
                (CHURCH_MUSIC.search(title + ". " + description) or
                 any(CHURCH_MUSIC.search(tag) for tag in tags)))


def venue_matches(venue, names):
    name = normalized(plain_text(venue).split(",", 1)[0])
    for candidate in names:
        identity = normalized(candidate)
        if identity == "tullikamari":
            identity = r"tullikamari(?:n)?"
        else:
            identity = re.escape(identity)
        if re.search(r"(?<!\w)" + identity + r"(?!\w)", name):
            return True
    return False


def child_age_recommendation(text):
    return any(int(match[1]) < 13 and (not match[2] or int(match[2]) < 13)
               for match in CHILD_AGE.finditer(text))


ENGLISH_PERFORMANCE = re.compile(
    r"\b(?:esityskieli\s*(?:on|:)?\s*englanti|"
    r"(?:esitys|näytelmä)\s+(?:esitetään|on|puhutaan)\s+(?:englanniksi|englannin\s+kielellä|englanninkielinen)|"
    r"esitetään\s+(?:englanniksi|englannin\s+kielellä)|"
    r"englanninkieli\w*\s+(?:teatteriesitys|esitys|näytelmä)|"
    r"(?:performed|presented|staged)\s+in\s+english|"
    r"(?:performance|play|show)\s+(?:is\s+)?in\s+english|"
    r"(?:performance\s+language|language\s+of\s+(?:the\s+)?(?:performance|play|show))\s*:\s*english|"
    r"english[- ]language\s+(?:performance|play|show))\b", re.I)
NOT_ENGLISH_PERFORMANCE = re.compile(
    r"\b(?:not\s+(?:(?:performed|presented|staged)\s+)?in\s+english|"
    r"ei\s+(?:esitetä\s+)?(?:englanniksi|englannin\s+kielellä|englanninkielinen))\b", re.I)


RUSSIAN_PERFORMANCE = re.compile(
    ENGLISH_PERFORMANCE.pattern.replace("english", "russian").replace("englanti", "venäjä")
    .replace("englanniksi", "venäjäksi").replace("englannin", "venäjän").replace("englanninkieli", "venäjänkieli")
    + r"|\b(?:спектакль|постановка|представление)\s+(?:идёт\s+|идет\s+)?на\s+русском(?:\s+языке)?\b"
    + r"|\bязык\s+(?:спектакля|постановки)\s*:\s*русский\b", re.I)
NOT_RUSSIAN_PERFORMANCE = re.compile(
    NOT_ENGLISH_PERFORMANCE.pattern.replace("english", "russian").replace("englanniksi", "venäjäksi")
    .replace("englannin", "venäjän").replace("englanninkielinen", "venäjänkielinen")
    + r"|\bне\s+на\s+русском\b", re.I)


def has_allowed_theatre_language(title, description, languages):
    text = title + ". " + description
    for language in languages:
        positive, negative, name = ((ENGLISH_PERFORMANCE, NOT_ENGLISH_PERFORMANCE, "english")
                                   if language == "en" else (RUSSIAN_PERFORMANCE, NOT_RUSSIAN_PERFORMANCE, "russian"))
        if not negative.search(text) and (positive.search(text) or re.search(r"\(in " + name + r"\)", title, re.I)):
            return True
    return False


def is_finnish_learning(title, description):
    # A concert description mentioning Finnish songs is not a language class.
    return bool(FINNISH_PRACTICE.search(title) or
                (LANGUAGE_ACTIVITY.search(title) and FINNISH_LEARNING.search(title)) or
                (LANGUAGE_ACTIVITY.search(title) and FINNISH_PRACTICE.search(description)))


def exclusion_reason(title, description, source_categories, config, performance_languages=(), venue=""):
    preferences = config.get("filters", {})
    title, description = plain_text(title), plain_text(description)
    tags = {tag.casefold() for tag in source_categories}
    text = title + ". " + description
    if preferences.get("exclude_nightclubs") and any(
            venue_matches(venue, [name]) for name in preferences.get("nightclub_venues", [])):
        return "nightclub venue"
    if preferences.get("exclude_standup") and (tags.intersection({"standup", "stand-up", "stand up"}) or STANDUP.search(text)):
        return "standup"
    if preferences.get("exclude_lectures") and LECTURES.search(text):
        return "lectures"
    if preferences.get("exclude_nightclubs") and NIGHTCLUB.search(text):
        return "nightclub events"
    if preferences.get("exclude_courses") and re.search(r'\bкурсы?\b', title, re.I):
        return "courses"
    if preferences.get("exclude_workshops") and re.search(r'\b(?:мастер-класс\w*|воркшоп\w*)\b', title, re.I):
        return "workshops"
    if any(re.search(pattern, title) for pattern in config.get("exclude_title_patterns", [])):
        return "custom title pattern"
    if any(keyword.casefold() in title.casefold() for keyword in preferences.get("exclude_title_keywords", [])):
        return "custom title keyword"
    if tags.intersection(tag.casefold() for tag in preferences.get("excluded_source_categories", [])):
        return "custom source category"
    if preferences.get("exclude_children") and (
            "kids and family" in tags or CHILDREN.search(title) or re.search(r"\bkoululai\w*", title, re.I)
            or re.search(r"\blast(?:en|e[nm])\s+elokuv\w*", description, re.I) or CHILD_AUDIENCE.search(description)
            or CHILD_SHOW.search(text) or child_age_recommendation(text)
            or (CHILD_PROJECT.search(description) and CHILD_PARTICIPATION.search(description))):
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
    if preferences.get("theatre_languages") and (
            tags.intersection({"theatre", "theater"}) or THEATRE.search(text) or re.search(r"\b\w*teatteri\w*\b", title, re.I)):
        if not (set(performance_languages).intersection(preferences["theatre_languages"])
                or has_allowed_theatre_language(title, description, preferences["theatre_languages"])):
            return "theatre without confirmed allowed performance language"
    music_tags = set(config.get("category_mapping", {}).get("music", []))
    if (preferences.get('church_choir_selection') == 'notable'
            and CHURCH_VENUE.search(plain_text(venue).split(',', 1)[0])
            and is_church_choir(title, description, tags)
            and not notable_church_choir(title, description, config)):
        return 'church choir without a recognized work or large-scale programme'
    if tags.intersection(music_tags) and preferences.get("music_selection") == "curated":
        artists = preferences.get("music_artists", [])
        venues = preferences.get("music_venues", [])
        if not (any(re.search(r"(?<!\w)" + re.escape(artist) + r"(?!\w)", title, re.I) for artist in artists)
                or venue_matches(venue, venues)
                or (preferences.get("allow_church_music") and church_music_eligible(title, description, tags, venue, config))):
            return "music outside curated artists or venues"
    return None


def event_exclusion_reason(event, config):
    municipalities = config["sources"].get(event.source, {}).get("municipalities", config["municipalities"])
    if event.municipality not in municipalities or event.category not in config["categories"]:
        return "area or category"
    tags = list(event.source_categories)
    if event.category == "music" and not set(tags).intersection(config["category_mapping"]["music"]):
        tags.append(config["category_mapping"]["music"][0])
    return exclusion_reason(event.title, event.description, tags, config, event.performance_languages, event.address or event.venue)
