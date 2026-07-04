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

**How I found the root cause:**
Traced from record_listening_event() into update_listening_streak() in
services/streak_service.py. Added a temporary debug print to confirm
today.weekday() was returning 6 on the Sunday call, then compared that
against the actual condition guarding the increment branch. Removed the
print once confirmed.

**The root cause:**
The increment branch read:
elif days_since_last == 1 and today.weekday() != 6:
Python's weekday() returns 6 for Sunday. This condition meant the streak
would only increment on a one-day gap if today was NOT a Sunday — so any
legitimate consecutive-day streak landing on a Sunday fell through to the
else branch and reset to 1 instead of incrementing.

**My fix and side-effect check:**
Removed the "and today.weekday() != 6" clause, leaving a plain
"one-day gap increments" rule. Ran the full tests/test_streaks.py suite
(all 5 pass, including the previously-failing Sunday test) and searched
the codebase for other uses of weekday()/isoweekday() to confirm no
other logic depended on the old Sunday-exclusion behavior.

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

**The root cause:**
The function ended with:
`return [song.to_dict() for song in songs[:-1]]`
`songs[:-1]` is a Python slice meaning "every item except the last one."
Since `songs` is already ordered ascending by `position`, the last item
in that list is always the actual last song in the playlist. This slice
unconditionally discarded it on every call, for every non-empty
playlist, regardless of length — it wasn't a query bug, it was a
post-query truncation that had nothing to do with fetching correct data.

**My fix and side-effect check:**
Removed the `[:-1]` slice, returning the full ordered list. Ran the full
`tests/test_playlists.py` suite: both previously-failing tests now pass,
and `test_empty_playlist_returns_empty_list` still passes (an empty list
sliced with `[:-1]` is still empty, so this edge case happened to look
correct even with the bug present — worth noting since a passing test
here didn't mean the code was right, just that it didn't exercise the
buggy path).

Searched the codebase for other callers of `get_playlist_songs()` and
found it used in `routes/playlists.py` (the real caller) and imported in
`services/notification_service.py`'s `add_to_playlist()` function — but
confirmed that import is never actually called there (a leftover,
unused import), so no other logic depended on the old, incorrect count.

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

**How I found the root cause:**
Opened services/notification_service.py and read rate_song() end to end.
Since the hint pointed to comparing it against a working pattern, read
add_to_playlist() (in the same file) immediately after -- both functions
share the same shape (look up song, look up acting user, perform the
write, commit), but only add_to_playlist() ends with a call to
create_notification(). rate_song() simply returned after its commit.

**The root cause:**
This isn't a broken condition or typo -- rate_song() never had a
create_notification() call added to it in the first place. The
notification-sending step that add_to_playlist() implements was left
out entirely when rate_song() was written, even though both functions
represent the same kind of event (a friend interacting with a shared
song) and the app's own notification system was already built to
handle exactly this case.

**My fix and side-effect check:**
Added a create_notification() call after the rating commit, using the
same self-action guard as add_to_playlist() (song.shared_by != user_id)
so a sharer rating their own song doesn't get a self-notification.
Verified: (1) a friend rating a song produces exactly 1 notification
for the sharer, (2) the sharer rating their own song produces 0, and
(3) updating an existing rating still notifies without errors. Searched
the codebase for other callers of rate_song() (routes/songs.py only) to
confirm nothing depended on the old, silent behavior.

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

**How I found the root cause:**
Opened services/feed_service.py and read get_friends_listening_now()
top to bottom. Found a single constant, RECENT_THRESHOLD = timedelta
(hours=24), controlling the recency filter -- confirmed by reading the
neighboring get_activity_feed() function, which explicitly has no
recency filter at all (its docstring says so directly), showing that
RECENT_THRESHOLD is the sole point of control for "Listening Now"
specifically.

**The root cause:**
The filter logic itself (listened_at >= cutoff, where cutoff = now minus
RECENT_THRESHOLD) is correct -- it does exactly what a 24-hour window
should do. The problem is the value of that threshold: 24 hours matches
a history/recap window, not what "Listening Now" should mean for a
feature intended to show real-time presence. Anyone who listened at any
point in the last full day, including yesterday afternoon, was treated
as if they were listening right now.

**My fix and side-effect check:**
Narrowed RECENT_THRESHOLD to 30 minutes. Verified: a listening event 20
hours old is now correctly excluded (0 results), while a fresh event a
few minutes old is still correctly included (1 result). Confirmed
get_activity_feed() is unaffected, since it doesn't reference
RECENT_THRESHOLD at all and is explicitly designed as the unfiltered,
longer-history counterpart to this feature.

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

**How I reproduced it:**
Ran pytest tests/test_search.py -v -- all 5 tests passed, including the
one specifically written to catch this bug. This did not mean the bug
was absent. Compared raw SQL against the ORM's output for a 3-tag song:
the equivalent raw SQL query returned 3 rows for that one song, but
search_songs() itself returned only 1.

**How I found the root cause:**
Opened services/search_service.py and read search_songs(). Noticed the
query joins Song against song_tags but never filters or selects
anything from that table -- the join contributes nothing to the WHERE
clause. Used an AI tool to explain a narrowed, already-diagnosed
question: why would SQLAlchemy's query API return 1 row when the
underlying SQL produces 3? Verified the explanation myself by running
the same join through SQLAlchemy's newer select()/scalars() API, which
does not auto-dedupe -- it returned 3 rows for the same data, proving
the row-multiplication is real and only hidden by legacy Query's
built-in behavior.

**The root cause:**
The join against song_tags multiplies each song's row once per
associated tag at the SQL level -- a song with 3 tags produces 3 raw
rows. The reason this isn't visible in the current output is that
db.session.query(Song).all() (SQLAlchemy's legacy Query API)
automatically de-duplicates full entity results by primary key. That
is incidental ORM behavior the query doesn't actually need or
reference anywhere -- the join serves no purpose in this function at
all, since tags are loaded separately via the Song.tags relationship.
Relying on this masking behavior instead of removing the unnecessary
join means the bug reappears immediately under a different query style
(e.g. 2.0-style select()), which is the direction SQLAlchemy itself
recommends moving toward.

**My fix and side-effect check:**
Removed the unused join against song_tags entirely, along with the
now-unused Tag and song_tags imports. Re-ran tests/test_search.py (all
5 pass) and re-ran the select()/scalars() comparison from my
reproduction against the fixed query -- it now returns exactly 1 row
for a 3-tag song, confirming the fix holds structurally rather than by
accident. Confirmed tags still appear correctly in results, since
to_dict() loads them via the independent Song.tags relationship,
unaffected by this change.