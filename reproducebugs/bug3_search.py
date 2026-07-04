import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from app import create_app, db

app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///mixtape.db"})
with app.app_context():
    # Raw SQL — exactly what the join in search_service.py produces
    raw = db.session.execute(
        db.text("""
            SELECT song.id, song.title
            FROM song
            LEFT OUTER JOIN song_tags ON song.id = song_tags.song_id
            WHERE song.title LIKE :q
        """),
        {"q": "%Crown%"}
    ).fetchall()

    print("RAW SQL rows returned:", len(raw))
    for row in raw:
        print(" -", row)

    # Now compare to what the actual service function returns
    from services.search_service import search_songs
    results = search_songs("Crown")
    print("\nsearch_songs() results:", len(results))
    for r in results:
        print(" -", r["title"])