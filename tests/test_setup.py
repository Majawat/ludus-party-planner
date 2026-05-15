"""Tests for the first-run onboarding wizard (Feature 1)."""
import pytest

from app import create_app
from models import SiteSettings, User, db as _db, utcnow


# ---------------------------------------------------------------------------
# Fixtures — fresh DB with NO setup complete (wizard not done)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_app():
    """App with empty DB — no admin, no setup_complete flag."""
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
def fresh_client(fresh_app):
    return fresh_app.test_client()


@pytest.fixture()
def app_with_admin_no_complete():
    """App with admin user but setup_complete not set to true."""
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
        admin = User(name="Admin", email="admin@example.com", is_admin=True, email_verified_at=utcnow())
        admin.set_password("adminpass123")
        _db.session.add(admin)
        _db.session.commit()
        yield app
        _db.drop_all()


@pytest.fixture()
def client_no_complete(app_with_admin_no_complete):
    return app_with_admin_no_complete.test_client()


# ---------------------------------------------------------------------------
# Guard tests
# ---------------------------------------------------------------------------

def test_setup_guard_redirects_any_route_when_no_admin(fresh_client):
    """With no admin and no setup_complete, ALL routes redirect to /setup."""
    for path in ["/", "/events", "/login", "/admin/"]:
        response = fresh_client.get(path)
        assert response.status_code == 302, f"{path} should redirect"
        assert "/setup" in response.headers["Location"], f"{path} should go to /setup"


def test_setup_guard_allows_static_files(fresh_client):
    """Static files are never redirected by the setup guard."""
    response = fresh_client.get("/static/css/ludus.css")
    # Will be 404 (file doesn't exist in test env), but NOT a redirect to /setup
    assert response.status_code != 302 or "/setup" not in response.headers.get("Location", "")


def test_setup_guard_allows_ping(fresh_client):
    response = fresh_client.get("/ping")
    assert response.status_code == 200


def test_setup_guard_redirects_when_setup_complete_false(client_no_complete):
    """Even with an admin, if setup_complete != 'true', redirect to /setup."""
    response = client_no_complete.get("/")
    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]


def test_setup_guard_passes_when_complete(app, client):
    """With admin + setup_complete=true (set by conftest), homepage is accessible."""
    response = client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Step 1: Create admin account
# ---------------------------------------------------------------------------

def test_setup_step1_get_returns_200(fresh_client):
    response = fresh_client.get("/setup")
    assert response.status_code == 200
    assert b"admin" in response.data.lower()


def test_setup_step1_creates_admin_user(fresh_client, fresh_app):
    response = fresh_client.post("/setup", data={
        "name": "Alice Admin",
        "email": "alice@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    }, follow_redirects=False)
    assert response.status_code == 302
    assert "/setup/site" in response.headers["Location"]

    with fresh_app.app_context():
        user = User.query.filter_by(email="alice@example.com").first()
        assert user is not None
        assert user.is_admin is True
        assert user.email_verified_at is not None


def test_setup_step1_rejects_duplicate_email(fresh_client, fresh_app):
    with fresh_app.app_context():
        existing = User(name="Existing", email="taken@example.com", is_admin=False)
        existing.set_password("pass")
        _db.session.add(existing)
        _db.session.commit()

    response = fresh_client.post("/setup", data={
        "name": "New Admin",
        "email": "taken@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    }, follow_redirects=False)
    assert response.status_code == 200
    assert b"already exists" in response.data


def test_setup_step1_rejects_mismatched_passwords(fresh_client):
    response = fresh_client.post("/setup", data={
        "name": "Admin",
        "email": "admin@example.com",
        "password": "securepass123",
        "confirm_password": "different123",
    })
    assert response.status_code == 200
    with fresh_client.application.app_context():
        assert User.query.count() == 0


# ---------------------------------------------------------------------------
# Step 2: Site settings
# ---------------------------------------------------------------------------

def _create_admin_via_step1(client):
    client.post("/setup", data={
        "name": "Alice Admin",
        "email": "alice@example.com",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })


def test_setup_step2_get_returns_200(fresh_client):
    _create_admin_via_step1(fresh_client)
    response = fresh_client.get("/setup/site")
    assert response.status_code == 200


def test_setup_step2_redirects_to_step1_if_no_admin(fresh_client):
    response = fresh_client.get("/setup/site")
    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]


def test_setup_step2_saves_site_settings(fresh_client, fresh_app):
    _create_admin_via_step1(fresh_client)
    response = fresh_client.post("/setup/site", data={
        "site_name": "My Awesome Events",
        "site_tagline": "Gaming nights",
        "contact_email": "",
        "ui_theme": "dracula",
    }, follow_redirects=False)
    assert response.status_code == 302
    assert "/setup/complete" in response.headers["Location"]

    with fresh_app.app_context():
        assert SiteSettings.get("site_name") == "My Awesome Events"
        assert SiteSettings.get("ui_theme") == "dracula"


# ---------------------------------------------------------------------------
# Step 3: Complete
# ---------------------------------------------------------------------------

def test_setup_complete_sets_flag(fresh_client, fresh_app):
    _create_admin_via_step1(fresh_client)
    fresh_client.get("/setup/complete")

    with fresh_app.app_context():
        assert SiteSettings.get("setup_complete") == "true"


def test_setup_complete_redirects_to_step1_if_no_admin(fresh_client):
    response = fresh_client.get("/setup/complete")
    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]


def test_setup_redirects_to_home_when_already_done(fresh_client, fresh_app):
    _create_admin_via_step1(fresh_client)
    with fresh_app.app_context():
        SiteSettings.set("setup_complete", "true")

    response = fresh_client.get("/setup")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


# ---------------------------------------------------------------------------
# CLI: seed-setup
# ---------------------------------------------------------------------------

def test_seed_setup_resets_flag(app):
    with app.app_context():
        SiteSettings.set("setup_complete", "true")
        assert SiteSettings.get("setup_complete") == "true"

    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-setup"])
    assert result.exit_code == 0
    assert "false" in result.output

    with app.app_context():
        assert SiteSettings.get("setup_complete") == "false"
