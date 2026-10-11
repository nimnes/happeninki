CREATE TABLE events (
  id TEXT PRIMARY KEY, url TEXT NOT NULL, venue TEXT NOT NULL, municipality TEXT NOT NULL,
  start TEXT NOT NULL, end TEXT NOT NULL, dates TEXT NOT NULL,
  date_only INTEGER NOT NULL, cancelled INTEGER NOT NULL
);
CREATE TABLE event_texts (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  language TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
  PRIMARY KEY (event_id, language)
);
CREATE TABLE favourites (
  user_id TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  language TEXT NOT NULL, PRIMARY KEY (user_id, event_id)
);
CREATE TABLE processed_updates (
  update_id INTEGER PRIMARY KEY,
  completed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
