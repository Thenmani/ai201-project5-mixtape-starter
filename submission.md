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

### Bug 1 — Listening streak keeps resetting
**How I reproduced it:**
Called update_listening_streak() directly with two consecutive datetimes —
Saturday 2024-06-15 (weekday()==5) then Sunday 2024-06-16 (weekday()==6).
Expected the streak to go 1 → 2 (consecutive-day increment). Got 1 → 1
instead — the streak did not increment when the second day was a Sunday.

### Bug 5 — Last song in a playlist never shows up
**How I reproduced it:**
Ran `pytest tests/test_playlists.py -v` — two tests failed:
`test_playlist_returns_all_songs` (expected 5 songs, got 4) and
`test_playlist_returns_songs_in_order` (expected `Track 5` in the result,
it was missing).

Confirmed manually against the seeded dev DB: queried the raw
`playlist_entries` table directly for a playlist and compared that count
against what `get_playlist_songs()` returned — the raw table had one more
row than the service function returned, and the missing song was always
the one in the highest `position` value (i.e., the last one).
No special data condition needed — reproduces on any non-empty playlist.

### Bug 4 — No notification when a song is rated
**How I reproduced it:**
Created a sharer and a rater, had the sharer share a song, then called
rate_song(rater.id, song.id, 5) directly. Checked get_notifications(sharer.id)
afterward — expected at least one notification informing the sharer their
song was rated, got 0.

For comparison, the working pattern (add_to_playlist) does call
create_notification() when a friend adds the sharer's song to a playlist —
rate_song() has no equivalent call, even though it follows the same
overall shape (look up song, look up acting user, perform the write, commit).

No special data condition needed — reproduces on the very first rating
by anyone other than the song's sharer.

### Bug 2 — Friends Listening Now shows people from yesterday
**How I reproduced it:**
Created a test user and one friend. Gave the friend a single listening
event timestamped 20 hours ago — old enough that no one would call it
"right now."

Called get_friends_listening_now() and checked the result: the friend
showed up as "listening now," even though their only activity was almost
a full day old.

**Why it happens:**
feed_service.py has a setting called RECENT_THRESHOLD, set to 24 hours.
This tells the app "treat anyone who listened in the last 24 hours as
currently listening." That window is way too wide for a feature that's
supposed to mean "right now" — it lets in anything from the last full
day, not just the last few minutes.

The code isn't broken in the sense of doing the wrong calculation — it's
doing exactly what it was told. The problem is the number itself (24
hours) doesn't match what "Listening Now" should actually mean to a user.

**Conditions needed:** none, really — just one friend with a listening
event somewhere under 24 hours old. No special setup required.

### Bug 3 — Same song shows up twice in search
**How I reproduced it:**
Ran pytest tests/test_search.py -v — surprisingly, all 5 tests passed,
including the one specifically written to catch this bug
(test_search_no_duplicates_multi_tag_song). This did not mean the bug
was absent.

Dug one level deeper by comparing raw SQL against the ORM's output for a
song with 3 tags ("Crown Heights Anthem"). Running the equivalent raw SQL
directly (the same join search_songs() uses) returned 3 rows for that one
song. But calling search_songs() itself returned only 1 result for the
same song.

**Why the test passes despite the bug being real:**
search_songs() joins Song against song_tags (a table with multiple rows
per song when a song has multiple tags) even though it never filters or
selects anything from that table. At the raw SQL level, this join
multiplies each song's row once per tag. SQLAlchemy's query API happens
to auto-deduplicate full model objects by primary key, which is why the
final Python result collapses back to 1 row and hides the problem from
both the test suite and the live endpoint.

**Condition needed to trigger:** a song with 2+ tags. Songs with 0 or 1
tag never produce more than 1 joined row, so they never expose this
gap — which is exactly why seed_data.py deliberately creates songs with
"3+ tags" to "expose Issue #3."