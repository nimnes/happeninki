import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from .models import Event

SCHEMA_VERSION = "1"


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                id TEXT PRIMARY KEY, canonical_key TEXT NOT NULL,
                payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
                eligible INTEGER NOT NULL, first_seen TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS canonical_events ON events(canonical_key);
            CREATE TABLE IF NOT EXISTS aliases(source_key TEXT PRIMARY KEY, event_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS translations(
                text_hash TEXT NOT NULL, language TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(text_hash, language));
            CREATE TABLE IF NOT EXISTS publications(
                event_id TEXT NOT NULL, language TEXT NOT NULL, channel_hash TEXT NOT NULL,
                message_id INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                PRIMARY KEY(event_id, language, channel_hash));
            CREATE TABLE IF NOT EXISTS suppressed_events(event_id TEXT PRIMARY KEY);
        """)
        version = self.get_meta("schema_version")
        if version and version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported state schema {version}")
        self.set_meta("schema_version", SCHEMA_VERSION)

    def close(self):
        self.connection.close()

    def get_meta(self, key):
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, str(value)))

    def reset(self):
        """Clear history locally; the caller checkpoints only after a complete scan."""
        with self.connection:
            for table in ("publications", "translations", "aliases", "events", "suppressed_events"):
                self.connection.execute(f"DELETE FROM {table}")
            self.connection.execute("DELETE FROM metadata WHERE key != 'schema_version'")

    def requeue_upcoming(self, events, today, end):
        """Promote current listings without deleting translation or send receipts."""
        promoted = 0
        with self.connection:
            for event in events:
                if event.cancelled or not event.overlaps(today, end):
                    continue
                alias = self.connection.execute("SELECT event_id FROM aliases WHERE source_key=?",
                                                (event.source_key,)).fetchone()
                if alias:
                    promoted += self.connection.execute(
                        "UPDATE events SET eligible=1 WHERE id=? AND eligible=0", (alias[0],)).rowcount
        return promoted

    def reconcile_selection(self, source, events, today, end):
        """Suppress old queued listings absent from a successful filtered scan.

        Keep receipts and eligibility intact so later preference changes can restore
        a listing without repeating a post. Never call this for a failed source.
        """
        selected = {event.source_key for event in events if event.source == source}
        with self.connection:
            for row in self.connection.execute("SELECT id, payload FROM events").fetchall():
                event = Event(**json.loads(row["payload"]))
                if event.source != source or not event.overlaps(today, end):
                    continue
                if event.source_key in selected:
                    self.connection.execute("DELETE FROM suppressed_events WHERE event_id=?", (row["id"],))
                else:
                    self.connection.execute("INSERT OR IGNORE INTO suppressed_events VALUES(?)", (row["id"],))

    def ingest(self, events, today, initial_end):
        first_launch = self.get_meta("initialized") is None
        with self.connection:
            for event in events:
                alias = self.connection.execute("SELECT event_id FROM aliases WHERE source_key=?", (event.source_key,)).fetchone()
                existing = self.connection.execute("SELECT * FROM events WHERE id=?", (alias[0],)).fetchone() if alias else None
                if existing:
                    old = Event(**json.loads(existing["payload"]))
                    if old.dates and event.dates:
                        # The API filters occurrences by the requested date window.
                        # Preserve historical dates so a rolling window isn't an edit.
                        past = [d for d in old.dates if date.fromisoformat(d["end"][:10]) < today]
                        merged = {d["start"]: d for d in past + event.dates}
                        event.dates = sorted(merged.values(), key=lambda d: d["start"])
                        event.start = event.dates[0]["start"]
                        event.end = max(d["end"] for d in event.dates)
                if not existing:
                    existing = self.connection.execute("SELECT * FROM events WHERE canonical_key=? LIMIT 1", (event.canonical_key,)).fetchone()
                event_id = existing["id"] if existing else uuid.uuid4().hex
                if existing:
                    # For an alias on a secondary source, retain the primary payload.
                    old = Event(**json.loads(existing["payload"]))
                    if old.source_key != event.source_key:
                        self.connection.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (event.source_key, event_id))
                        continue
                    eligible = existing["eligible"]
                else:
                    eligible = int(not first_launch or event.overlaps(today, initial_end))
                self.connection.execute("""INSERT INTO events VALUES(?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET canonical_key=excluded.canonical_key,
                    payload=excluded.payload, fingerprint=excluded.fingerprint""",
                    (event_id, event.canonical_key, json.dumps(asdict(event), ensure_ascii=False),
                     event.fingerprint, eligible, today.isoformat()))
                self.connection.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (event.source_key, event_id))
            if first_launch:
                self.connection.execute("INSERT INTO metadata VALUES('initialized',?)", (today.isoformat(),))
                self.connection.execute("INSERT INTO metadata VALUES('initial_window_end',?)", (initial_end.isoformat(),))

    def pending(self, today, languages, channel_hashes, now=None):
        result = []
        for row in self.connection.execute("""SELECT * FROM events WHERE eligible=1
                AND id NOT IN (SELECT event_id FROM suppressed_events)"""):
            event = Event(**json.loads(row["payload"]))
            if not event.active_on(today):
                continue
            if now is not None and not event.date_only and "T" in event.end:
                finish = datetime.fromisoformat(event.end)
                if finish.tzinfo is not None and finish <= now:
                    continue
            pending = []
            for language in languages:
                publication = self.publication(row["id"], language, channel_hashes[language])
                if publication is None and event.cancelled:
                    continue
                if publication is None or publication["fingerprint"] != event.fingerprint:
                    pending.append(language)
            if pending:
                result.append((row["id"], event, pending))
        return sorted(result, key=lambda item: (item[1].start, item[1].title))

    def publication(self, event_id, language, channel_hash):
        return self.connection.execute("SELECT * FROM publications WHERE event_id=? AND language=? AND channel_hash=?",
                                       (event_id, language, channel_hash)).fetchone()

    def mark_published(self, event_id, language, channel_hash, message_id, fingerprint):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO publications VALUES(?,?,?,?,?)",
                                    (event_id, language, channel_hash, message_id, fingerprint))

    def translation(self, event, language):
        row = self.connection.execute("SELECT payload FROM translations WHERE text_hash=? AND language=?",
                                      (event.text_fingerprint, language)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_translation(self, event, language, translation):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO translations VALUES(?,?,?)",
                                    (event.text_fingerprint, language, json.dumps(translation, ensure_ascii=False)))

    def snapshot(self, target):
        with sqlite3.connect(target) as destination:
            self.connection.backup(destination)


def validate_database(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("State database failed integrity check")
        version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not version or version[0] != SCHEMA_VERSION:
            raise ValueError("State database has an unsupported schema")
        if not connection.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone():
            raise ValueError("State database is not initialized")
