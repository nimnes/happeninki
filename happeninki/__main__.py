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
from .http import HttpClient, RemoteError
from .models import next_month
from .releases import ReleaseState
from .sources import collect
from .store import Store, validate_database
from .telegram import Telegram, TelegramThrottled, build_message, channel_hash
from .translator import TranslationUnavailable, Translator
from .classifier import Classifier, comparison, PROMPT_VERSION
from .selection import rank_pending, decision_key

LOG = logging.getLogger("happeninki")


def publish_pending(store, config, translator, telegram, today, checkpoint, deadline, now=None, blocked_sources=(), classifier=None):
    enabled_languages = [language for language in config["languages"] if telegram.channels.get(language)]
    hashes = {language: channel_hash(telegram.channels[language]) for language in enabled_languages}
    selection = config.get('selection', {})
    pending = store.pending(today, enabled_languages, hashes, now=now, include_updates=selection.get('enabled', False))
    pending = [item for item in pending if item[1].source not in blocked_sources]
    pending, decisions = rank_pending(store, pending, config, today, hashes, now=now)
    report = selection_report(store, pending, decisions, config, classifier, deadline)
    report['delivery_holds'] = store.delivery_holds(hashes)
    if report['delivery_holds']:
        LOG.warning('%d uncertain deliveries held; check the channels before resolving them', len(report['delivery_holds']))
    write_selection_report(config, report)
    LOG.info("%d events queued for publication or update", len(pending))
    sent, failures = 0, 0
    for event_id, event, languages in pending[:config["max_events_per_run"]]:
        # Select all available channel deliveries together. A failure in the first
        # language must not let the remaining language expire as editorial overflow.
        selected_new_delivery = False
        for language in languages:
            if (not store.publication(event_id, language, hashes[language])
                    and store.delivery_status(event_id, language, hashes[language]) not in {'pending', 'unknown'}
                    and (not selection.get('enabled') or store.quota_used(
                        datetime.now(ZoneInfo(config['timezone'])).date(), hashes[language]) < selection['daily_limit'])):
                store.set_delivery(event_id, language, hashes[language], 'pending', event.fingerprint)
                selected_new_delivery = True
        if selected_new_delivery:
            checkpoint(store)  # Preserve the choice even if translation is interrupted.
        for language in languages:
            if time.monotonic() >= deadline:
                LOG.warning("Run time budget reached; remaining events stay queued")
                return sent, failures
            try:
                publication = store.publication(event_id, language, hashes[language])
                quota_day = datetime.now(ZoneInfo(config['timezone'])).date()
                if not publication and selection.get('enabled') and store.quota_used(quota_day, hashes[language]) >= selection['daily_limit']:
                    info = decisions[event_id] | {'status': 'deferred', 'reason': 'daily posting limit'}
                    store.record_editorial(event_id, decision_key(event, config), 'deferred', info)
                    decisions[event_id].update(info)
                    continue
                message_kind = publication["message_kind"] if publication else "text"
                image_url = event.image_url if not publication or message_kind == "photo" else ""
                translation = store.translation(event, language)
                if translation is None:
                    translation = translator.translate(event, language)
                    store.cache_translation(event, language, translation)
                photo = bool(image_url) or message_kind == "photo"
                try:
                    message = build_message(event, translation, language, today, 1024 if photo else 4096)
                except ValueError:
                    if publication and message_kind == "photo":
                        raise
                    image_url = ""
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
            reservation = None
            if not publication and selection.get('enabled'):
                quota_day = datetime.now(ZoneInfo(config['timezone'])).date()
                reservation = store.reserve_post(quota_day, hashes[language], event_id, selection['daily_limit'])
                if not reservation:
                    continue
            try:
                extra = {"image_url": image_url, "message_kind": message_kind} if image_url or message_kind == "photo" else {}
                for attempt in range(4):
                    try:
                        current_day = datetime.now(ZoneInfo(config['timezone'])).date()
                        if reservation and current_day != quota_day:
                            store.finish_reservation(reservation, 'released')
                            reservation = store.reserve_post(current_day, hashes[language], event_id, selection['daily_limit'])
                            checkpoint(store)
                            if not reservation:
                                return sent, failures
                            quota_day = current_day
                        if not publication:
                            # Persist the hold before the network call. A crash or
                            # lost reply must not cause a resend in the next run.
                            store.set_delivery(event_id, language, hashes[language], 'unknown', event.fingerprint)
                            checkpoint(store)
                        message_id = telegram.publish(language, message, publication["message_id"] if publication else None, **extra)
                        break
                    except TelegramThrottled as exc:
                        if not publication:
                            store.set_delivery(event_id, language, hashes[language], 'pending', event.fingerprint)
                        checkpoint(store)
                        delay = exc.retry_after
                        if (attempt == 3 or not isinstance(delay, (int, float)) or isinstance(delay, bool)
                                or delay <= 0 or delay + 15 >= deadline - time.monotonic()):
                            if reservation:
                                store.finish_reservation(reservation, 'released')
                                checkpoint(store)
                            LOG.warning("Telegram cooldown exceeds retry or run budget (retry_after=%s); remaining events stay queued", delay)
                            return sent, failures
                        LOG.warning("Telegram rate limit: waiting %s seconds before retrying %s (%s)", delay, event.source_key, language)
                        remaining = delay + 1
                        while remaining > 0:
                            pause = min(remaining, 60)
                            time.sleep(pause)
                            remaining -= pause
            except Exception as exc:
                # A transport timeout can mean Telegram accepted the message.
                # Stop the run; never repeatedly submit it in this run.
                LOG.error("Telegram failed for %s (%s): %s", event.source_key, language, exc)
                if not publication and isinstance(exc, RemoteError) and exc.status in {400, 401, 403, 404}:
                    store.set_delivery(event_id, language, hashes[language], 'pending', event.fingerprint)
                    if reservation:
                        store.finish_reservation(reservation, 'released')
                report['delivery_holds'] = store.delivery_holds(hashes)
                write_selection_report(config, report)
                checkpoint(store)
                return sent, failures + 1
            store.mark_published(event_id, language, hashes[language], message_id, event.fingerprint,
                                 getattr(telegram, "last_message_kind", "text"))
            if reservation:
                store.finish_reservation(reservation, 'sent')
            if event_id in decisions:
                info = decisions[event_id] | {'status': 'sent' if not publication else 'updated'}
                store.record_editorial(event_id, decision_key(event, config), info['status'], info)
                decisions[event_id].update(info)
            # If persistence fails, abort before any further messages are sent.
            checkpoint(store)
            sent += 1
            LOG.info("%s %s (%s)", "Updated" if publication else "Published", event.source_key, language)
    write_selection_report(config, report)
    checkpoint(store)
    return sent, failures


def selection_report(store, pending, decisions, config, classifier, deadline):
    report = {'classifier_mode': config.get('selection', {}).get('classifier_mode', 'off'),
              'classifier_model': config['ollama']['model'], 'prompt_version': PROMPT_VERSION,
              'classification_requested': bool(classifier),
              'decisions': decisions, 'classifications': []}
    if not classifier:
        return report
    for event_id, event, _ in pending[:config['selection']['classification_budget']]:
        if time.monotonic() + 180 >= deadline:
            break
        item = {'event_id': event_id, 'source_key': event.source_key, 'title': event.title}
        try:
            facts = classifier.classify(event, store)
            item.update(facts=facts, comparison=comparison(facts, config))
        except Exception as exc:
            LOG.warning('Classification unavailable for %s (%s); shadow publication unaffected', event.source_key, type(exc).__name__)
            item.update(comparison='unavailable', error=type(exc).__name__)
            report['classifications'].append(item)
            break  # Avoid exhausting the allowance or repeatedly hitting an outage.
        report['classifications'].append(item)
    return report


def write_selection_report(config, report):
    if config.get('selection', {}).get('enabled'):
        destination = Path('data/selection.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(args):
    config = load_config(args.config)
    http = HttpClient()
    today = datetime.now(ZoneInfo(config["timezone"])).date()
    deadline = time.monotonic() + config["run_budget_seconds"]
    channels = {language: os.getenv(f"TELEGRAM_CHANNEL_{language.upper()}", "").strip() for language in config["languages"]}
    remote = ReleaseState(http, os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")) if args.release_state else None
    translator = Translator(http, config["ollama"], os.getenv("OLLAMA_API_KEY")) if args.mode == "publish" or args.translate else None
    telegram = Telegram(http, os.getenv("TELEGRAM_BOT_TOKEN"), channels) if args.mode == "publish" else None
    classifier = (Classifier(http, config['ollama'], os.getenv('OLLAMA_API_KEY'))
                  if config.get('selection', {}).get('classifier_mode') == 'shadow'
                  and os.getenv('OLLAMA_API_KEY') and (args.mode == 'publish' or getattr(args, 'classify', False)) else None)

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
            config['_published_source_keys'] = store.published_source_keys() if not args.reset_state else set()
            events, source_failures = collect(config, http, today, scan_end)
            if source_failures and (first_launch or args.requeue_upcoming):
                raise RuntimeError("Collection incomplete; reset/requeue/initialization not applied and no posts sent. Retry after fixing the source failures.")
            if args.reset_state:
                LOG.warning("Resetting event history; previously published events may be posted again")
                store.reset()
            store.ingest(events, today, initial_end)
            if config.get('selection', {}).get('enabled'):
                # Baseline listings enter the queue when their notice window opens.
                store.requeue_upcoming(events, today, today + timedelta(days=config['selection']['lead_days']))
            blocked_sources = set(source_failures) | {
                source for source, settings in config["sources"].items() if not settings["enabled"]}
            for source, settings in config["sources"].items():
                if settings["enabled"] and source not in source_failures:
                    store.reconcile_selection(source, events, today, scan_end)
            if args.requeue_upcoming:
                promoted = store.requeue_upcoming(events, today, scan_end)
                LOG.info("Requeued %d baseline listings; successful publication receipts preserved", promoted)
            if args.mode == "preview":
                # Without channels, preview still works for both languages offline.
                preview_languages = [language for language in config["languages"] if channels[language]] or config["languages"]
                hashes = {language: channel_hash(channels[language] or f"preview-{language}") for language in preview_languages}
                pending = store.pending(today, preview_languages, hashes,
                                        now=datetime.now(ZoneInfo(config["timezone"])), include_updates=config.get('selection', {}).get('enabled', False))
                pending = [item for item in pending if item[1].source not in blocked_sources]
                pending, decisions = rank_pending(store, pending, config, today, hashes,
                                                 now=datetime.now(ZoneInfo(config['timezone'])))
                report = selection_report(store, pending, decisions, config, classifier, deadline)
                report['delivery_holds'] = store.delivery_holds(hashes)
                slots = {lang: max(0, config.get('selection', {}).get('daily_limit', args.limit) - store.quota_used(today, hashes[lang])) for lang in preview_languages}
                selected = []
                for event_id, event, languages in pending[:config['max_events_per_run']]:
                    available = []
                    for language in languages:
                        if store.publication(event_id, language, hashes[language]):
                            available.append(language)
                        elif slots[language] > 0:
                            available.append(language)
                            slots[language] -= 1
                    if available:
                        selected.append((event_id, event, available))
                    if event_id in decisions:
                        decisions[event_id]['selected_languages'] = available
                        decisions[event_id]['deferred_languages'] = [lang for lang in languages if lang not in available]
                        if decisions[event_id]['status'] == 'candidate':
                            decisions[event_id]['status'] = 'selected' if available else 'deferred'
                output = []
                for event_id, event, languages in selected[:args.limit]:
                    item = {"event": asdict(event), "pending_languages": languages}
                    if event_id in decisions:
                        item['selection'] = decisions[event_id]
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
                    "selected_events": len(selected),
                    "reset_state": args.reset_state, "requeue_upcoming": args.requeue_upcoming,
                    "source_failures": source_failures, "selection_report": report, "events": output}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                LOG.info("Preview saved: %s (%d of %d pending events)", destination, len(output), len(pending))
                return int(bool(source_failures))
            checkpoint = remote.checkpoint if remote else lambda _: None
            checkpoint(store)  # Persist baseline and queue before the first send.
            sent, failures = publish_pending(store, config, translator, telegram, today, checkpoint, deadline,
                                            now=datetime.now(ZoneInfo(config["timezone"])), blocked_sources=blocked_sources, classifier=classifier)
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
    parser.add_argument("--classify", action="store_true", help="Use Ollama for advisory preview classification")
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
