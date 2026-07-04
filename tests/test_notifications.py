"""
tests/test_notifications.py — Mixtape

Tests for notification creation logic.
"""

import pytest
from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_song(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        db.session.add(sharer)
        db.session.flush()

        song = Song(title="Some Song", artist="Someone", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        yield {"sharer": sharer, "song": song}


def test_rating_a_friends_song_notifies_the_sharer(app, sharer_and_song):
    """Rating someone else's song should notify the original sharer."""
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        song = sharer_and_song["song"]

        rater = User(username="rater", email="rater@example.com")
        db.session.add(rater)
        db.session.commit()

        rate_song(rater.id, song.id, 5)

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 1
        assert notifs[0]["type"] == "song_rated"


def test_rating_your_own_song_does_not_notify_yourself(app, sharer_and_song):
    """A user rating their own shared song should not self-notify."""
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        song = sharer_and_song["song"]

        rate_song(sharer.id, song.id, 4)

        notifs = get_notifications(sharer.id)
        assert notifs == []


def test_updating_a_rating_notifies_again(app, sharer_and_song):
    """Changing an existing rating should also notify the sharer."""
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        song = sharer_and_song["song"]

        rater = User(username="rater", email="rater@example.com")
        db.session.add(rater)
        db.session.commit()

        rate_song(rater.id, song.id, 5)
        rate_song(rater.id, song.id, 3)

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 2