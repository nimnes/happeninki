# Häppeninki

Find something worth going out for in Tampere.

Häppeninki discovers local events and shares short Russian and English summaries
on Telegram, making it easier to explore the city's cultural life without having
to follow several Finnish event calendars.

It covers **Tampere, Nokia, Ylöjärvi, Pirkkala, Kangasala and Lempäälä**, with a focus
on concerts, exhibitions, festivals, food campaigns and other cultural events.
The Russian channel also includes Art Master events in **Jyväskylä and Helsinki**.
The area and categories can be extended as the project grows.

By default, it skips children's activities, book clubs and reading sessions
(including reading to dogs), general courses, workshops, bingo, pub quizzes and
karaoke, standup, lectures (including lecture-concerts) and nightclub events.
Music is restricted to the curated concert venues or favourite artists below.
Finnish-language learning is an exception to the course filter.
Theatre plays are included only when their performance language is English or
Russian; unknown languages are excluded. Art Master's calendar is treated as
Russian-language by default. Children’s daycare art projects are excluded even
when the source labels them only as exhibitions.

## How it works

Once a day, at **09:00 Helsinki time**, the bot checks its event sources, identifies
new listings, ranks eligible events and publishes at most **seven new posts per
channel per Helsinki day**. Each selected event receives a separate translated post.
Each post includes a short description, compact dates and times, a clickable
Google Maps address, and a link to the original listing. Dates and location appear
in separate blocks. Postal codes and repeated city names are removed; paid prices
and price ranges are shown, while zero-euro prices are hidden.

When an event has a cover image, new posts include it above the description.
Long summaries are shortened to fit a photo caption, keeping dates, location and
links. If Telegram cannot load the image or the details cannot fit, the bot posts
text. Existing text posts continue to be updated as text; photo posts are updated
in place.

Russian and English channels are independently optional: run either one or both.
The bot remembers what it has posted in each channel and can update existing
messages when an event changes or the source reports a cancellation.

On the first launch, it queues events happening within the **next month**, including
exhibitions already open. After that, it looks for newly discovered events up to
six months ahead (180 days). Listings already known beyond the initial month are
saved and become eligible when they enter the 30-day publication window.
Daily slots are shared by scheduled and manual runs. Unselected listings are
reconsidered for three days, then skipped until their details or preferences change.
Once chosen for delivery, translation failures and confirmed send rejections remain
retryable while the event is eligible; they do not expire as unselected overflow.
Recurring listings use their next unfinished occurrence for the notice window and
timing score, preserving historical dates in saved state.
This avoids gradually publishing the entire backlog. Edits and cancellations
to previously published posts do not use new-post slots.

| Source | Coverage | Channels |
| --- | --- | --- |
| [Tampere event calendar](https://tapahtumat.tampere.fi) | Tampere and the configured surrounding municipalities | Russian and English |
| [SYÖ!-viikot](https://syoviikot.fi) | Restaurant campaigns in the configured municipalities | Russian and English |
| [Art Master](https://ru.art-master.fi/afisha) | Tampere area, Jyväskylä and Helsinki | Russian only |

Coverage depends on what organizers list in these sources. Art Master's extra
cities do not expand the Tampere calendar scan. Children's shows remain excluded,
and touring shows without a published street address link to their city instead.
The SYÖ! connection is included, but still needs verification with a published
campaign when the next one becomes available.

## Event selection and comparison

The approved music venues, favourite-artist list and church classical/choir/jazz
exception still determine music eligibility. Ranking then favors stated church
music preferences, approved programme contexts, complete location information
and useful lead time. Its points express ordering, not popularity or probabilities.
There is no internet popularity lookup and no minimum-score gate in this first
version; these require evaluation before changing the approved eligibility rules.
Duplicate listings with the same normalized title, city, venue and occurrence
starts compete for one post, even when their advertised end times differ.

The `[selection]` settings control the seven-post limit, 30-day notice window,
three-day reconsideration period and advisory classifier. `enabled = false`
restores the original queue behavior; `classifier_mode = "off"` disables only
model classification. Classification uses the configured Ollama model and key,
with at most five candidate classifications per run. It extracts audience, format
and actual performance language, requires source quotes, and caches results by
source content, model and prompt version. Unknown fields stay unknown. A failed
classifier stops further classification for that run and leaves rule-based
publication unchanged. Model decisions are **comparison only** until evaluated.

For a read-only comparison without posting:

```sh
python -m happeninki --mode preview --classify --output data/preview.json
```

Ordinary previews work without model access. `--classify` explicitly enables
model calls for preview; translations remain a separate `--translate` option.
The workflow offers `classify_preview` and saves comparison JSON as an artifact.
Preview includes scores, reasons, proposed languages, deferred languages and
model findings. A publish run also saves `data/selection.json` for inspection.
Without configured channels, preview assumes empty demonstration channel quotas;
restore release state and configure the real channels to see their remaining slots.

Classification and editorial records are stored separately from message and
translation fingerprints, so advisory score changes do not edit Telegram posts.
Existing databases gain additive tables without losing publication receipts.
Posting slots and delivery holds are saved before sending. Uncertain transport
failures retain their slot and block automatic resends across runs, including when
a message was sent but its receipt could not be checkpointed. Confirmed refusals
remain retryable and can release the slot. Resetting
event history preserves the daily ledger. The ledger starts with this version;
older receipts contain no posting dates and cannot reconstruct earlier daily usage.
Production scheduling is serialized by the existing workflow concurrency group.

### Resolving an uncertain delivery

Preview and publication reports include `delivery_holds` with the source identity
and affected language. Check that channel manually before resolving a hold, and
run resolution while publication is idle. Use the same channel environment variable
as publication. These commands update state without sending Telegram messages.

If the message exists, record its actual ID (and add `--message-kind photo` for
a photo post):

```sh
python -m happeninki.resolve_delivery tampere:EVENT_ID --language ru --message-id 123 --release-state
```

If you have confirmed that no message was posted, permit a later normal retry:

```sh
python -m happeninki.resolve_delivery tampere:EVENT_ID --language ru --retry --release-state
```

For local state, omit `--release-state` and optionally supply `--database PATH`.
Older unresolved daily reservations are held conservatively too, because their
outcome cannot be reconstructed. A confirmed existing message keeps its quota
slot; a confirmed unsent attempt releases it. Subsequent source changes still edit
the confirmed post normally.

## A small bot without a server

```text
Event sources → Collection and filtering → Ollama translation → Telegram
                         ↕
                   Saved event history
```

GitHub Actions runs the bot on a schedule. Ollama Cloud translates the event
text, and a small database saved in a GitHub release keeps track of events and
published messages between runs.

There is no always-running server or separate database service to host. Modest
usage can fit within GitHub and Ollama's free allowances, though translation
capacity depends on the model and your account. If the allowance runs out,
unpublished events stay queued for a later run.

Telegram posts are paced to avoid rate limits. If Telegram requests a cooldown,
the bot waits and retries when there is enough time left; otherwise, it saves
progress and leaves the remaining events for a later run. No state reset is needed.

## Set up your own

You will need:

- A GitHub repository containing this project, with Actions enabled.
- A Telegram bot created through [@BotFather](https://t.me/BotFather).
- One or two Telegram channels, with the bot added as an administrator allowed
  to post and edit its messages.
- An Ollama Cloud account, API key and an accessible model.

### 1. Add your settings

In your repository, open **Settings → Secrets and variables → Actions** and add:

| Secret | What to enter |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | The token from BotFather |
| `TELEGRAM_CHANNEL_RU` | Russian channel ID or `@username`, if used |
| `TELEGRAM_CHANNEL_EN` | English channel ID or `@username`, if used |
| `OLLAMA_API_KEY` | Your Ollama Cloud API key |

Set at least one channel. Leave the other secret empty or omit it to disable
that language. Numeric channel IDs are preferable because they stay the same
when a channel's username changes. Keep tokens in secrets, never in source files.

The default model is `gemma4:31b-cloud`. To choose another, add an Actions
**variable** named `OLLAMA_MODEL` with a model available to your account.

### 2. Preview the posts

Open **Actions → Publish Tampere events → Run workflow**.
Choose `mode=preview` and enable `translate_preview` to inspect up to ten
translated event posts. Download the run's output artifact and open
`preview.json` to see the results.

Preview sends nothing to Telegram and leaves saved history unchanged.
Translated previews use your Ollama allowance.

### 3. Start publishing

Run the workflow again with `mode=publish` and `initialize=true` for the first
launch. After that, leave `initialize` off. Daily runs will publish automatically;
you can also run the workflow manually to continue a backlog.

Each run handles up to 100 events across the enabled channels, subject to an
18-minute bot time budget and available translation allowance. Check the Actions
results to see whether a run succeeded. To continue a backlog, run `mode=publish`
again with the initialization, reset and requeue options left off.

### Reset or include more upcoming events

The manual workflow also offers:

| Option | What it does |
| --- | --- |
| `reset_state` | Clears history and repeats the first-month launch. Existing Telegram posts remain, so events can be posted again. |
| `requeue_upcoming` | Queues currently listed upcoming events up to six months ahead, including those skipped by the initial month window. Preserves successful posts. |

Enable both to start fresh and queue all collected upcoming events within that
six-month window. Use `mode=preview` to inspect the effect first. On subsequent
runs, leave both options off so the bot resumes its queue instead of resetting it again.

## Make it yours

[config.toml](config.toml) controls the municipalities, event categories, filters,
model and publishing limits. The daily posting time is set in the
[publishing workflow](.github/workflows/publish.yml).

The `[filters]` section lets you choose what you want to see:

```toml
[filters]
exclude_children = true
exclude_reading = true
exclude_courses = true
allow_finnish_learning = true
exclude_workshops = true
exclude_games = true
exclude_standup = true
exclude_lectures = true
exclude_nightclubs = true
nightclub_venues = ["Fame Club", "Bar Ihku", "Viihdemaailma Ilona"]
music_selection = "curated"
music_venues = ["Nokia Arena", "Tampere-talo", "Tampereen Jäähalli", "Tavara-asema", "Tullikamari", "G Livelab"]
music_artists = []
allow_church_music = true
church_choir_selection = "notable"
church_choir_works = ["Mozart: Requiem", "Handel: Messiah", "Orff: Carmina Burana"]
theatre_languages = ["en", "ru"]
excluded_source_categories = []
exclude_title_keywords = []
```

Set an exclusion to `false` to include that type again. For a stricter selection,
add source category names such as `"dance"` to `excluded_source_categories`, or
title phrases such as `"open mic"` to `exclude_title_keywords`. Reading exclusions
also cover listings tagged as literature; library concerts and exhibitions can
still be included. Clear Finnish-learning titles can be included even when they
are listed outside the usual cultural categories.

`music_selection = "curated"` admits music only at `music_venues` or when the title
names an artist in `music_artists`. The venue list includes Nokia Arena,
Tampere-talo, Tampereen Jäähalli, Tavara-asema, Tullikamari and G Livelab.
Venue is a proxy for a curated concert programme, not proof that an artist is popular; favourite artists can be added
without depending on their venue. Set `music_selection = "all"` to remove this
restriction. With `allow_church_music = true`, classical, choir and jazz music
at church venues is also included, based on the venue name and genre wording in
the title, description or source categories. Finnish terms such as “kirkko”,
“klassinen”, “kuoro” and “jazz” are recognized, along with English equivalents.
Church choirs additionally require a recognized programme or clear scale evidence
under `church_choir_selection = "notable"`. The configurable `church_choir_works`
list includes Mozart/Verdi Requiems, Messiah, Carmina Burana, Bach passions and
Beethoven's Ninth, with Finnish and English title variants. A bare “Requiem”
requires a matching configured composer. A symphony orchestra, massed choir,
at least three choirs, at least 100 singers, or a national/international choir
festival can also qualify a larger production. These are conservative signals
from the current event's title or advertised programme, not verified audience sizes.
Generic praise and repertoire mentioned only in a past-performance biography do
not qualify. Ordinary church choirs are excluded even when described as classical,
and do not receive the church preference bonus. Existing published messages still
receive updates. Set `church_choir_selection = "all"` to restore the broader rule.
Organ recitals and chamber music also count as classical music. Other genres
at churches still need a listed venue or favourite artist. Set the option to
`false` to disable this exception. Nightclub, children, lecture and other exclusions
still take priority.
`nightclub_venues` excludes known nightclub locations even without nightlife
wording. A concert venue having “Klubi” in its name does not alone make it a
nightclub. Age recommendations under 13 also identify children’s listings.

These rules reject unsuitable listings rather than postponing them in a lower
ranked backlog. No popularity score is inferred from marketing language or page
view counts. The publishing batch limit remains a separate operational setting.

`theatre_languages` keeps theatre listings only when the title or description
explicitly says the performance is in English or Russian, for example "performed
in English", "esityskieli: venäjä", or "спектакль на русском языке". Unknown languages
are excluded. Translated listings, titles, or subtitles alone do not establish the
performance language. Use `["en"]` or `["ru"]` to allow just one language, or `[]`
to include theatre in any language.

Each source can be disabled with `enabled = false`. Art Master's
`[sources.art_master]` section has its own `municipalities` and
`delivery_languages`, so its coverage and channel selection can be changed
independently. Its `performance_languages = ["ru"]` setting is a source-level
assumption, not language metadata verified for each show. Set it to `[]` to
require an explicit performance-language statement per listing.

New preferences apply to previously queued events too, without resetting history.
They do not delete messages already posted to Telegram. These are category and
text rules rather than a personal recommendation engine, so preview the results
and adjust them as you discover what you enjoy.

To explore the sources locally, install Python 3.12 and run:

```sh
python3 -m happeninki --mode preview
```

This saves a preview to `data/preview.json` and needs no Telegram or Ollama
credentials. For local translation or publishing, supply the settings listed in
[.env.example](.env.example) through your environment; `.env` files are not loaded
automatically. Python package installation is not required.

## Things to keep in mind

The project is still young. Source interfaces can change, category filters may
need tuning, and automated translations can make mistakes. Original listings
remain the place to check details before attending an event.

GitHub's scheduler can delay runs. Public repositories may also have schedules
disabled after 60 days without activity, so check Actions periodically. If a run
reports a database upload failure, keep its recovery artifact before retrying:
it may contain publication history needed to avoid duplicate posts.
