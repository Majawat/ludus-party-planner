import json
import pytest
from datetime import datetime

from app import create_app
from models import User, Event, TicketType, db as _db, utcnow


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "MAIL_SUPPRESS_SEND": True,
        "MAIL_DEFAULT_SENDER": "test@example.com",
        "SECRET_KEY": "test-secret-key",
    })
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    user = User(
        name="Admin",
        email="admin@example.com",
        is_admin=True,
        email_verified_at=utcnow(),
    )
    user.set_password("adminpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture()
def regular_user(app):
    user = User(
        name="Regular",
        email="user@example.com",
        is_admin=False,
        email_verified_at=utcnow(),
    )
    user.set_password("userpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture()
def unverified_user(app):
    user = User(
        name="Unverified",
        email="unverified@example.com",
        is_admin=False,
        email_verified_at=None,
    )
    user.set_password("unverifiedpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture()
def published_event(app):
    event = Event(
        name="Test LAN Party",
        slug="test-lan-party",
        type="lan",
        status="published",
        short_description="A test event.",
        description="<p>Full description here.</p>",
        start_datetime=datetime(2026, 8, 7, 18, 0, 0),
        end_datetime=datetime(2026, 8, 9, 18, 0, 0),
        location="Test Venue",
        seating_enabled=True,
        registration_open=True,
    )
    _db.session.add(event)
    _db.session.commit()
    return event


@pytest.fixture()
def draft_event(app):
    event = Event(
        name="Secret Draft Event",
        slug="secret-draft",
        type="board_game",
        status="draft",
        short_description="Not visible.",
        description="<p>Draft content.</p>",
        start_datetime=datetime(2026, 9, 1, 18, 0, 0),
        end_datetime=datetime(2026, 9, 2, 18, 0, 0),
        location="Nowhere",
        seating_enabled=False,
        registration_open=False,
    )
    _db.session.add(event)
    _db.session.commit()
    return event


@pytest.fixture()
def past_event(app):
    event = Event(
        name="Past Board Game Night",
        slug="past-board-game-night",
        type="board_game",
        status="published",
        short_description="Already happened.",
        description="<p>Past event description.</p>",
        start_datetime=datetime(2025, 11, 1, 10, 0, 0),
        end_datetime=datetime(2025, 11, 1, 22, 0, 0),
        location="Old Venue",
        seating_enabled=False,
        registration_open=False,
    )
    _db.session.add(event)
    _db.session.commit()
    return event


@pytest.fixture()
def ticket_type(app, published_event):
    tt = TicketType(
        event_id=published_event.id,
        name="Weekend Pass",
        price=20.00,
        quantity_total=30,
        seatable=True,
        includes_lodging=False,
        valid_days=json.dumps(["2026-08-07", "2026-08-08", "2026-08-09"]),
        max_per_user=1,
        is_active=True,
    )
    _db.session.add(tt)
    _db.session.commit()
    return tt
