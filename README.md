# Häppeninki

Tampere-area events posted daily to separate Russian and English Telegram channels.
Runs on Python 3.12 using only the standard library: no server, database service,
or dependency installation is required.

## Behavior

- Scans at **09:00 Europe/Helsinki**, including daylight-saving changes.
- Covers Tampere, Nokia, Ylöjärvi, Pirkkala, Kangasala and Lempäälä.
- Includes music, exhibitions, festivals, food campaigns and cultural events.
- Publishes a separate post for each listing in each language.
- First launch queues events overlapping **today through the same date next month**,
  including exhibitions already open. It records later listings as a silent baseline.
- Later scans announce newly discovered listings up to the configured discovery horizon
  (365 days by default). Existing baseline listings beyond the initial month stay silent.
- Groups multiple performance dates under one listing. Separate venues/listings can have
  separate posts. Category tags and title exclusions remove routine classes; editorial
  relevance is rule-based, so some borderline listings may need extra exclusion patterns.
- Updates previously published messages when source content changes, including an explicit
  cancellation. Missing listings are not assumed cancelled.
- Tracks Russian and English sends independently and caches translations. A failure in
  one language does not repeat the successful post in the other.
- Limits each run to 100 queued events and an 18-minute soft processing budget. A large
  first-launch backlog or exhausted Ollama allowance resumes on later/manual runs.

## Sources

1. **Tampere event calendar**: the public JSON collection interface used by
   [tapahtumat.tampere.fi](https://tapahtumat.tampere.fi). Verified with live data on
   5 October 2026. Municipalities are selected using the calendar's area IDs. This
   frontend interface is not a versioned third-party API and may change.
2. **SYÖ!-viikot**: the website's public current/next campaign endpoint. A published
   campaign generates one post per configured participating municipality, linking to
   the current restaurants/offers rather than copying every offer. The endpoint returned
   `null` during verification; positive campaign parsing is covered by a synthetic test
   and should be checked when the next campaign appears.

Each post links to its source. Coverage depends on what organizers publish; this does
not crawl every venue or social network. No images are reposted. The public frontend
endpoints were verified, but their long-term access/reuse guarantees are not established.

## Local preview

```sh
python3 -m happeninki --mode preview
```

The result is `data/preview.json`: source details, queue counts and pending languages.
Preview writes no persistent event history and sends nothing to Telegram. If a local
database exists, preview uses a temporary copy. Without channel settings, preview treats
both languages as unpublished; use the real settings to preview the actual queue.

To preview ten translated posts, provide `OLLAMA_API_KEY` in the environment:

```sh
python3 -m happeninki --mode preview --translate --limit 10
```

`.env.example` documents settings; `.env` is **not automatically loaded**. Export values
in your shell or use your preferred environment loader. Do not paste tokens into code.

## GitHub setup

1. Push the project to the repository's default branch.
2. Create a bot through Telegram's **@BotFather**, create two channels, and add the bot
   as an administrator with permission to post/edit its own messages.
3. In **Settings → Secrets and variables → Actions**, add these repository secrets:

   | Secret | Value |
   | --- | --- |
   | `TELEGRAM_BOT_TOKEN` | BotFather token |
   | `TELEGRAM_CHANNEL_RU` | Russian channel `@username` or numeric channel ID |
   | `TELEGRAM_CHANNEL_EN` | English channel `@username` or numeric channel ID |
   | `OLLAMA_API_KEY` | Ollama Cloud API key |

   Prefer numeric channel IDs so a username change does not reset channel identity.
   Optionally set the repository variable `OLLAMA_MODEL` to a model your account can
   access. The default is `gemma4:31b-cloud`; verify access with a translated preview.
4. Run **Publish Tampere events** manually with `mode=preview`. Enable translated
   preview to inspect both languages (this consumes your Ollama allowance).
5. Run manually with `mode=publish` and **initialize=true** for the first launch.
   Use a test bot/channels first if you want to inspect actual Telegram rendering.
6. Subsequent manual runs use **initialize=false**. Scheduled runs publish automatically.

GitHub provides the repository token for release storage automatically; no personal
access token is needed in Actions. Before initialization, scheduled runs refuse to
create empty history. This prevents accidental reset/reposting if the release is lost.

## Release-based state

The `events-db` GitHub release stores **immutable, timestamped SQLite snapshots**.
New uploads do not remove the preceding snapshot. The bot restores the newest snapshot
and checks its integrity and GitHub digest when available. A failed download stops the
run instead of falling back to empty or older history. After a successful run, the three
newest snapshots remain.

State is checkpointed before publication and after every successful send/edit. If an
upload fails, further sends stop. A seven-day Actions recovery artifact also preserves
the runner's database and preview, including on a failed run; it is supplementary
recovery storage, not the source of truth.

SQLite contains normalized public event descriptions, aliases, translations and
publication history. Credentials and raw source contact metadata are excluded. Channel
identifiers are hashed. Release snapshots will be publicly downloadable if the repository
becomes public. Keep credentials in GitHub secrets.

Telegram sending and GitHub persistence cannot form one atomic transaction. A crash or
ambiguous timeout after Telegram accepts a send but before state is saved can cause a
duplicate on the next run. Do not blindly rerun after an upload failure: recover the
runner's database first if it includes posts missing from the latest release.

### Recovery

For a failed upload, download `run-output-<run-id>` from that Actions run and retain its
`events.db`. Validate it before uploading as a new snapshot:

```sh
python3 -c 'from happeninki.store import validate_database; validate_database("data/events.db")'
```

With `GITHUB_TOKEN` (a token scoped to this repository with contents write access) and
`GITHUB_REPOSITORY` exported:

```sh
python3 -m happeninki.recover --database data/events.db
```

This only uploads the validated database; it does not send Telegram messages. Use the
most recent runner database that includes all successfully sent posts. Restoring an
older snapshot may repeat newer posts. Never delete the state release to clear errors.

## Configuration and extension

Edit `config.toml` to adjust municipalities, categories, title exclusions, discovery
horizon, Ollama model and processing limits. Adding a municipality requires its calendar
area ID in `[sources.tampere.areas]` as well as its name in `municipalities`. Change
posting time in `.github/workflows/publish.yml`.

Add source adapters in `happeninki/sources.py`. Each returns normalized `Event` objects
with stable source IDs. Exact normalized title + municipality + address + date range
deduplicates across sources; ambiguous near matches remain separate to avoid suppressing
different concerts. The original source ID remains the update identity when dates change.

## Cost and operational limits

Daily runs should fit GitHub's private-repository free allowance at modest volume;
minutes are shared with your other repositories/workflows. Ollama usage depends on your
account/model allowance and is not unlimited. On access/quota failure, events remain
queued and the workflow fails visibly. No paid service fallback is enabled.

When the repository becomes public, GitHub can disable scheduled workflows after 60
days without repository activity. Do not assume snapshot uploads keep scheduling enabled.
Check Actions periodically or use an external scheduler if needed. Scheduled runs can
also be delayed; 09:00 is the requested start time, not a delivery guarantee.

## Verification

```sh
python3 -m unittest discover -s tests -v
```

Tests cover real calendar schemas, date-window merging, first-launch selection,
cross-source duplicates, language-specific retries, translation caching, cancellation,
rolling-date changes, failed checkpoints and restore errors. Tests never contact live
services. Live source checks use preview mode; live Ollama and Telegram checks require
your account credentials.
