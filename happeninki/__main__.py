import argparse
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .http import HttpClient
from .models import next_month
from .releases import ReleaseState
from .sources import collect
from .store import Store, validate_database
from .telegram import Telegram, build_message, channel_hash
from .translator import TranslationUnavailable, Translator

LOG = logging.getLogger("happeninki")


def publish_pending(store, config, translator, telegram, today, checkpoint, deadline, now=None):
    enabled_languages = [language for language in config["languages"] if telegram.channels.get(language)]
    hashes = {language: channel_hash(telegram.channels[language]) for language in enabled_languages}
    pending = store.pending(today, enabled_languages, hashes, now=now)
    LOG.info("%d events queued for publication or update", len(pending))
    sent, failures = 0, 0
    for event_id, event, languages in pending[:config["max_events_per_run"]]:
        for language in languages:
            if time.monotonic() >= deadline:
                LOG.warning("Run time budget reached; remaining events stay queued")
                return sent, failures
            try:
                translation = store.translation(event, language)
                if translation is None:
                    translation = translator.translate(event, language)
                    store.cache_translation(event, language, translation)
                message = build_message(event, translation, language, today)
            except TranslationUnavailable:
                LOG.error("Ollama is unavailable or its allowance is exhausted; remaining events stay queued")
                checkpoint(store)
                return sent, failures + 1
            except Exception as exc:
                LOG.error("Translation/formatting failed for %s (%s): %s", event.source_key, language, exc)
                failures += 1
                continue
            publication = store.publication(event_id, language, hashes[language])
            try:
                message_id = telegram.publish(language, message, publication["message_id"] if publication else None)
            except Exception as exc:
                # A transport timeout can mean Telegram accepted the message.
                # Stop the run; never repeatedly submit it in this run.
                LOG.error("Telegram failed for %s (%s): %s", event.source_key, language, exc)
                checkpoint(store)
                return sent, failures + 1
            store.mark_published(event_id, language, hashes[language], message_id, event.fingerprint)
            # If persistence fails, abort before any further messages are sent.
            checkpoint(store)
            sent += 1
            LOG.info("%s %s (%s)", "Updated" if publication else "Published", event.source_key, language)
    checkpoint(store)
    return sent, failures


def run(args):
    config = load_config(args.config)
    http = HttpClient()
    today = datetime.now(ZoneInfo(config["timezone"])).date()
    deadline = time.monotonic() + config["run_budget_seconds"]
    channels = {language: os.getenv(f"TELEGRAM_CHANNEL_{language.upper()}", "").strip() for language in config["languages"]}
    remote = ReleaseState(http, os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")) if args.release_state else None
    translator = Translator(http, config["ollama"], os.getenv("OLLAMA_API_KEY")) if args.mode == "publish" or args.translate else None
    telegram = Telegram(http, os.getenv("TELEGRAM_BOT_TOKEN"), channels) if args.mode == "publish" else None

    # Preview always uses a temporary copy, including translation caches.
    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "events.db" if args.mode == "preview" else Path(args.database)
        if args.mode == "preview":
            if remote:
                remote.restore(db_path, initialize=True)
            elif Path(args.database).exists():
                validate_database(args.database)
                shutil.copy2(args.database, db_path)
        elif remote:
            remote.restore(db_path, initialize=args.initialize or args.reset_state)
        elif not db_path.exists() and not (args.initialize or args.reset_state):
            raise RuntimeError("Local state is missing; use --initialize only for the first launch")
        elif db_path.exists():
            validate_database(db_path)
        store = Store(db_path)
        try:
            first_launch = args.reset_state or store.get_meta("initialized") is None
            initial_end = next_month(today)
            scan_end = today + timedelta(days=config["discovery_days"])
            LOG.info("Scanning %s to %s%s", today, scan_end, " (first-launch posts limited to one month)" if first_launch else "")
            events, source_failures = collect(config, http, today, scan_end)
            if source_failures and (first_launch or args.requeue_upcoming):
                raise RuntimeError("Collection incomplete; reset/requeue/initialization not applied and no posts sent. Retry after fixing the source failures.")
            if args.reset_state:
                LOG.warning("Resetting event history; previously published events may be posted again")
                store.reset()
            store.ingest(events, today, initial_end)
            if args.requeue_upcoming:
                promoted = store.requeue_upcoming(events, today, scan_end)
                LOG.info("Requeued %d baseline listings; successful publication receipts preserved", promoted)
            if args.mode == "preview":
                # Without channels, preview still works for both languages offline.
                preview_languages = [language for language in config["languages"] if channels[language]] or config["languages"]
                hashes = {language: channel_hash(channels[language] or f"preview-{language}") for language in preview_languages}
                pending = store.pending(today, preview_languages, hashes,
                                        now=datetime.now(ZoneInfo(config["timezone"])))
                output = []
                for _, event, languages in pending[:args.limit]:
                    item = {"event": asdict(event), "pending_languages": languages}
                    if translator:
                        item["messages"] = {}
                        for language in languages:
                            translation = store.translation(event, language) or translator.translate(event, language)
                            item["messages"][language] = build_message(event, translation, language, today)
                    output.append(item)
                destination = Path(args.output)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps({"first_launch": first_launch, "scan_start": today.isoformat(),
                    "scan_end": scan_end.isoformat(), "initial_window_end": initial_end.isoformat(),
                    "matching_listings": len(events), "pending_events": len(pending),
                    "reset_state": args.reset_state, "requeue_upcoming": args.requeue_upcoming,
                    "source_failures": source_failures, "events": output}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                LOG.info("Preview saved: %s (%d of %d pending events)", destination, len(output), len(pending))
                return int(bool(source_failures))
            checkpoint = remote.checkpoint if remote else lambda _: None
            checkpoint(store)  # Persist baseline and queue before the first send.
            sent, failures = publish_pending(store, config, translator, telegram, today, checkpoint, deadline,
                                            now=datetime.now(ZoneInfo(config["timezone"])))
            if remote:
                remote.prune()
            LOG.info("Finished: %d Telegram posts/updates; %d processing failures; %d source failures", sent, failures, len(source_failures))
            return int(bool(failures or source_failures))
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description="Discover and publish Tampere-area events")
    parser.add_argument("--mode", choices=("preview", "publish"), default="preview")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--database", default="data/events.db")
    parser.add_argument("--release-state", action="store_true", help="Restore/checkpoint state using GitHub Releases")
    parser.add_argument("--initialize", action="store_true", help="Explicitly allow first-launch state creation")
    parser.add_argument("--reset-state", action="store_true", help="Clear history and repeat first launch; may duplicate posts. Preview only simulates this.")
    parser.add_argument("--requeue-upcoming", action="store_true", help="Queue all collected upcoming events within the discovery horizon, preserving successful posts")
    parser.add_argument("--translate", action="store_true", help="Translate preview entries without publishing")
    parser.add_argument("--limit", type=int, default=10, help="Maximum preview entries")
    parser.add_argument("--output", default="data/preview.json")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        return run(args)
    except Exception as exc:
        LOG.error("Run stopped: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
