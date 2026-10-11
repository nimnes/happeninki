# Personal Telegram favourites

This Worker handles private user interactions; GitHub Actions continues collecting,
translating and posting events. D1 stores a public event catalogue and private
favourites keyed by Telegram user ID. No user favourites are copied into GitHub
release assets. Users save through an event-specific bot link, then use `/events`
or the Telegram menu. The channel's Save button always stays the same for everyone.

## Deploy on the free plan

Use Node.js 24 or newer. From this directory:

```sh
npm ci
npm test
npx wrangler login
npx wrangler d1 create happeninki-favourites
cp wrangler.example.jsonc wrangler.jsonc
```

Replace `REPLACE_WITH_DATABASE_ID` in the ignored `wrangler.jsonc` with the ID
returned by D1 creation. If the account already has this database, reuse it rather
than creating another. For multiple accounts, add the intended `account_id` to the
local configuration. Do not enable a paid plan.

```sh
npx wrangler d1 migrations apply happeninki-favourites --remote
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put FAVOURITES_SYNC_SECRET
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
npx wrangler deploy
```

Use the existing publishing bot token. Generate two different random secrets of
at least 32 characters for catalogue sync and webhook verification. Keep them in
a password manager; paste them only at the hidden secret prompts. The webhook
secret may contain letters, digits, underscores and hyphens. No credentials belong
in source files or commands. Cloudflare supplies a `workers.dev` address; no domain
purchase is required. Secrets and D1 are bound to this Worker only.

After deployment, verify `https://YOUR-WORKER.workers.dev/health` returns `{"ok":true}`.
Then run this from the repository root. It prompts for credentials without echoing:

```sh
python3 cloudflare/configure_telegram.py --url https://YOUR-WORKER.workers.dev
```

This registers `/telegram` with Telegram using a webhook secret, configures a
private-chat menu in English/Russian, and verifies the webhook. It preserves pending
updates. An existing different webhook requires an explicit `--replace-webhook`
after review. It uses one webhook connection to serialize interactions and reduce
replay races. The publishing job uses `sendMessage` and is compatible with webhooks;
do not add a competing `getUpdates` consumer for this bot.

Finally, in the GitHub repository's Actions settings, set:

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `TELEGRAM_BOT_USERNAME` | Exact username reported by setup, without `@` |
| Variable | `FAVOURITES_WORKER_URL` | HTTPS Worker origin, without `/telegram` |
| Secret | `FAVOURITES_SYNC_SECRET` | Same sync secret used by the Worker |

Keep the existing `TELEGRAM_BOT_TOKEN` secret. Only enable these three favourites
settings together after the Worker is ready. Until then, publishing works as before.
No Cloudflare API credential is needed by the daily publication workflow.

For this installation the Worker origin is
`https://happeninki-favourites.nimnes.workers.dev` and the bot username is
`happeninki_bot`. Account/database IDs and credentials stay in ignored local files.
The ignored `secrets.json` can be used with `wrangler secret bulk secrets.json`
instead of the three interactive `secret put` commands. Never commit that file.
The Telegram setup helper also accepts `--secrets-file cloudflare/secrets.json`
when run from the repository root.

## Behaviour and verification

New individual posts receive a localized **Save event** button. Sunday 18:00
weekly digests have source links only, with no save buttons. Existing posts
gain buttons only when a normal event update is sent; this feature does not resend
old events or rewrite channel history.

Event metadata and its translation are registered through authenticated `/events`
before a button is posted. A sync failure leaves the affected delivery pending and
publishes no broken Save button. Changes and cancellations are reflected when the
publisher updates the post; the list reflects the last synced catalogue, not live
source availability. Cancelled events cannot be newly saved and existing saved
cancellations are marked. Save buttons are removed from updated cancelled posts.
Recurring schedules retain all dates, including historical occurrences. Catalogue
requests are bounded to 1 MiB rather than a fixed occurrence count; Telegram
webhook requests remain bounded to 64 KiB.

A user may save up to 100 events. Duplicate saves (including the other channel's
language version) update one entry. `/events` lists upcoming events chronologically,
five per page, with source links and removal buttons. Ended events are cleaned from
that user's list when they open it or save another event. `/delete_me` requires a
private confirmation and removes only that user's saved rows. `/privacy` explains
storage. English/Russian responses follow the save link or Telegram UI language.

To test live, use your own private bot chat: save an actual newly posted event,
open `/events`, save it again, and remove it. A second Telegram account should see
an independent list. Do not send artificial events to production channels.

Webhook requests require Telegram's secret header; sync requests require a separate
Bearer secret. There is no public API for viewing user favourites. Commands and
callbacks work only in a private chat whose ID matches the sender. Queries bind all
values, and displayed text is escaped. Incoming message bodies and names are not
logged or persisted. Completed webhook IDs are retained for seven days to suppress
Telegram redelivery; a partially failed reply can repeat its confirmation, but not
create duplicate favourites. Cloudflare infrastructure still handles requests under
its own data policies.

## Development and rollback

```sh
npm test
npx wrangler deploy --dry-run --config wrangler.example.jsonc
```

Tests use SQLite with a D1 adapter and mocked Telegram calls. Deployment dry-run
bundles the actual Worker. For local Wrangler testing, put test-only secrets in
ignored `.dev.vars` and apply migrations with `--local`. Never point a local test
at a production Telegram bot or D1 database.

To disable publisher buttons, remove all three favourites settings in GitHub.
Existing Save links still work while the Worker remains deployed. To stop private
handling too, explicitly remove the webhook with Telegram's `deleteWebhook` method.
Do not delete D1 during a routine rollback: doing so destroys personal lists.
