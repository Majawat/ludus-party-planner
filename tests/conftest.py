import json
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app import create_app
from models import User, Event, Registration, Seat, TicketType, SiteSettings, UserPlatformAccount, db as _db, utcnow


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
        # Satisfy the setup guard: every test DB starts with a completed setup state.
        _db.session.add(SiteSettings(key="setup_complete", value="true"))
        setup_admin = User(
            name="Setup Admin",
            email="setup@test.invalid",
            is_admin=True,
            email_verified_at=utcnow(),
        )
        setup_admin.set_password("irrelevant")
        _db.session.add(setup_admin)
        _db.session.commit()
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
        start_datetime=utcnow() + timedelta(days=90),
        end_datetime=utcnow() + timedelta(days=92),
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
        start_datetime=utcnow() + timedelta(days=120),
        end_datetime=utcnow() + timedelta(days=121),
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


@pytest.fixture()
def seat(app, published_event):
    s = Seat(event_id=published_event.id, label="Seat 1", display_order=1)
    _db.session.add(s)
    _db.session.commit()
    return s


@pytest.fixture()
def registration(app, regular_user, published_event, ticket_type):
    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    _db.session.add(reg)
    _db.session.commit()
    return reg


@pytest.fixture()
def oauth_user(app):
    """A user created via OAuth with no password and a linked Discord account."""
    user = User(
        name="OAuth User",
        email="oauth@example.com",
        email_verified_at=utcnow(),
    )
    # password_hash stays None (OAuth-only user)
    _db.session.add(user)
    _db.session.flush()
    acct = UserPlatformAccount(
        user_id=user.id,
        platform="discord",
        username="OAuthUser#1234",
        platform_user_id="999888777",
    )
    _db.session.add(acct)
    _db.session.commit()
    return user


@pytest.fixture()
def discord_settings(app):
    """Seed the Discord OAuth client credentials in SiteSettings."""
    SiteSettings.set("discord_oauth_client_id", "test-discord-client-id")
    SiteSettings.set("discord_oauth_client_secret", "test-discord-client-secret")


@pytest.fixture()
def second_user(app):
    user = User(
        name="Second User",
        email="second@example.com",
        is_admin=False,
        email_verified_at=utcnow(),
    )
    user.set_password("secondpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture()
def past_ticket_type(app, past_event):
    tt = TicketType(
        event_id=past_event.id,
        name="Past Pass",
        price=0.00,
        quantity_total=30,
        seatable=False,
        includes_lodging=False,
        valid_days=json.dumps(["2025-11-01"]),
        max_per_user=1,
        is_active=True,
    )
    _db.session.add(tt)
    _db.session.commit()
    return tt


@pytest.fixture()
def past_registration(app, regular_user, past_event, past_ticket_type):
    reg = Registration(
        user_id=regular_user.id,
        event_id=past_event.id,
        ticket_type_id=past_ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    _db.session.add(reg)
    _db.session.commit()
    return reg


@pytest.fixture()
def mock_print_generator(monkeypatch):
    import sys
    import types
    fake = types.ModuleType("print_generator")
    fake.generate_nametag = lambda name: b"fake_stl_content"
    fake.generate_nameplate = lambda name, year: b"fake_3mf_content"
    fake.get_print_name = lambda user: (
        getattr(user, "gamertag", None)
        or getattr(user, "first_name", None)
        or "TEST"
    ).upper()
    sys.modules["print_generator"] = fake
    yield
    if "print_generator" in sys.modules:
        del sys.modules["print_generator"]
