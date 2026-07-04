import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, get_notifications

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
with app.app_context():
    db.create_all()

    sharer = User(username="sharer", email="sharer@example.com")
    rater = User(username="rater", email="rater@example.com")
    db.session.add_all([sharer, rater])
    db.session.flush()

    song = Song(title="Some Song", artist="Someone", shared_by=sharer.id)
    db.session.add(song)
    db.session.commit()

    # A friend rates the sharer's song
    rate_song(rater.id, song.id, 5)

    notifs = get_notifications(sharer.id)
    print("Notifications for sharer after a friend RATED their song:", len(notifs))