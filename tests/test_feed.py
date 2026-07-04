"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def friends(app):
    """Two friends and a song they can log listening events against."""
    with app.app_context():
        me = User(username="me", email="me@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([me, friend])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=me.id))

        song = Song(title="Some Song", artist="Someone", shared_by=me.id)
        db.session.add(song)
        db.session.commit()

        yield {"me": me, "friend": friend, "song": song}


def _log_listen(user_id, song_id, minutes_ago):
    now = datetime.now(timezone.utc)
    event = ListeningEvent(
        user_id=user_id, song_id=song_id, listened_at=now - timedelta(minutes=minutes_ago)
    )
    db.session.add(event)
    db.session.commit()


def test_friend_listening_a_few_minutes_ago_shows_up(app, friends):
    """A friend who listened 10 minutes ago should appear as currently listening."""
    with app.app_context():
        _log_listen(friends["friend"].id, friends["song"].id, minutes_ago=10)
        result = get_friends_listening_now(friends["me"].id)
        assert len(result) == 1
        assert result[0]["friend"]["username"] == "friend"


def test_friend_who_listened_yesterday_does_not_show_up(app, friends):
    """
    A friend whose only listening event was 20 hours ago should NOT
    appear in Listening Now -- this is the bug: a 24-hour window let
    stale listens masquerade as live presence.
    """
    with app.app_context():
        _log_listen(friends["friend"].id, friends["song"].id, minutes_ago=20 * 60)
        result = get_friends_listening_now(friends["me"].id)
        assert result == []


def test_friend_at_the_threshold_boundary_is_excluded(app, friends):
    """A listen from just over 30 minutes ago should be excluded."""
    with app.app_context():
        _log_listen(friends["friend"].id, friends["song"].id, minutes_ago=31)
        result = get_friends_listening_now(friends["me"].id)
        assert result == []


def test_friend_just_inside_threshold_is_included(app, friends):
    """A listen from just under 30 minutes ago should be included."""
    with app.app_context():
        _log_listen(friends["friend"].id, friends["song"].id, minutes_ago=29)
        result = get_friends_listening_now(friends["me"].id)
        assert len(result) == 1


def test_no_friends_listening_returns_empty_list(app, friends):
    """No recent events at all should return an empty feed, not an error."""
    with app.app_context():
        result = get_friends_listening_now(friends["me"].id)
        assert result == []