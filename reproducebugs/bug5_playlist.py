import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app import create_app, db
from models import Playlist, playlist_entries
from services.playlist_service import get_playlist_songs

app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///mixtape.db"})
with app.app_context():
    playlist = db.session.query(Playlist).first()
    print("Playlist:", playlist.name)

    # How many songs were actually inserted into this playlist's entries?
    actual_count = db.session.query(playlist_entries).filter_by(playlist_id=playlist.id).count()
    print("Songs actually in playlist_entries table:", actual_count)

    # What does the service function return?
    songs = get_playlist_songs(playlist.id)
    print("Songs returned by get_playlist_songs():", len(songs))
    for s in songs:
        print("  -", s["title"])