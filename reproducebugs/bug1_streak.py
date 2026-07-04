from app import create_app, db
from models import User
from services.streak_service import update_listening_streak
from datetime import datetime, timezone

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
with app.app_context():
    db.create_all()
    u = User(username="test", email="t@example.com")
    db.session.add(u)
    db.session.commit()

    saturday = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 5
    sunday   = datetime(2024, 6, 16, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 6

    update_listening_streak(u, saturday)
    print("after Saturday:", u.listening_streak)  # expect 1

    update_listening_streak(u, sunday)
    print("after Sunday:", u.listening_streak)    # expect 2 — see what you actually get