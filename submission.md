# Mixtape Bug Hunt — Codebase Map

## Main files

- **app.py** — Flask app factory. Creates the app, configures the DB,
  registers the 4 blueprints (songs, playlists, users, feed), calls
  db.create_all(). Single entry point for both the dev server and tests.

- **models.py** — All SQLAlchemy models: User, Song, Tag, ListeningEvent,
  Rating, Playlist, Notification, plus 3 association tables:
  - `friendships` — symmetric many-to-many on User (both directions inserted)
  - `song_tags` — many-to-many between Song and Tag
  - `playlist_entries` — many-to-many between Playlist and Song, with extra
    columns (position, added_by, added_at) — songs have explicit ordering,
    not just insertion order.

- **routes/** — 4 blueprints (songs, playlists, users, feed). Every route
  parses input, calls exactly one service function, and converts a
  ValueError into a 400/404 JSON error. No business logic lives here.

- **services/** — where all the logic actually lives:
  - streak_service.py — listening streak increment/reset rules
  - feed_service.py — "Friends Listening Now" + longer activity feed
  - search_service.py — song search by title/artist
  - notification_service.py — creates/reads Notifications; also owns
    rate_song()
  - playlist_service.py — playlist creation + ordered song retrieval

- **seed_data.py** — populates 5 users, a friend graph, 25 songs (split into
  0/1/3+ tag groups), 3 playlists, and a mix of very-recent + hours-old
  listening events.

- **tests/** — one file per service, in-memory SQLite via a pytest fixture.

## Pattern I noticed

Every route delegates immediately to a service function — routes only do
input parsing and response formatting. All business logic (and presumably
all 5 bugs) lives in services/.

## Data flow — user rates a song

1. Client: POST /songs/<song_id>/rate with {user_id, score}
2. routes/songs.py::rate() parses input, calls
   notification_service.rate_song(user_id, song_id, score)
3. rate_song() validates score 1-5, loads the Song and rating User, checks
   for an existing Rating (unique constraint on user_id+song_id) — updates
   it if found, creates one if not, commits.
4. Route returns rating.to_dict() as JSON, 201.