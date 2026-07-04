import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now
from datetime import datetime, timedelta, timezone

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
with app.app_context():
    db.create_all()

    me = User(username="me", email="me@example.com")
    friend = User(username="friend", email="friend@example.com")
    db.session.add_all([me, friend])
    db.session.flush()

    db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))
    db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=me.id))

    song = Song(title="Old Song", artist="Someone", shared_by=me.id)
    db.session.add(song)
    db.session.flush()

    now = datetime.now(timezone.utc)

    event = ListeningEvent(user_id=friend.id, song_id=song.id, listened_at=now - timedelta(hours=20))
    db.session.add(event)
    db.session.commit()

    result = get_friends_listening_now(me.id)
    print("Friends shown as LISTENING NOW:", len(result))
    for r in result:
        print(" -", r["friend"]["username"], "| listened_at:", r["listened_at"])