# Häppeninki

Find something worth going out for in Tampere.

Häppeninki discovers local events and shares short Russian and English summaries
on Telegram, making it easier to explore the city's cultural life without having
to follow several Finnish event calendars.

It covers **Tampere, Nokia, Ylöjärvi, Pirkkala, Kangasala and Lempäälä**, with a focus
on concerts, exhibitions, festivals, food campaigns and other cultural events.
The area and categories can be extended as the project grows.

## How it works

Once a day, at **09:00 Helsinki time**, the bot checks its event sources, identifies
new listings, translates them and publishes a separate post for each event.
Each post includes a short description, dates, location, price when available,
and a link to the original listing.

Russian and English channels are independently optional: run either one or both.
The bot remembers what it has posted in each channel and can update existing
messages when an event changes or the source reports a cancellation.

On the first launch, it queues events happening within the **next month**, including
exhibitions already open. After that, it looks for newly discovered events up to
a year ahead. Large backlogs are published in batches, so the first launch may
need several runs.

Events come from the [Tampere event calendar](https://tapahtumat.tampere.fi) and
[SYÖ!-viikot](https://syoviikot.fi). Coverage depends on what organizers list there.
The SYÖ! connection is included, but still needs verification with a published
campaign when the next one becomes available.

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

Each run handles up to 100 events, subject to its time budget and available
translation allowance. Check the Actions results to see whether a run succeeded.

### Reset or include more upcoming events

The manual workflow also offers:

| Option | What it does |
| --- | --- |
| `reset_state` | Clears history and repeats the first-month launch. Existing Telegram posts remain, so events can be posted again. |
| `requeue_upcoming` | Queues currently listed upcoming events up to a year ahead, including those skipped by the initial month window. Preserves successful posts. |

Enable both to start fresh and queue all collected upcoming events within that
year. Use `mode=preview` to inspect the effect first. On subsequent runs, leave
both options off so the bot resumes its queue instead of resetting it again.

## Make it yours

[config.toml](config.toml) controls the municipalities, event categories, filters,
model and publishing limits. The daily posting time is set in the
[publishing workflow](.github/workflows/publish.yml).

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
