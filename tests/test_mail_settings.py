from unittest.mock import patch, MagicMock

import pytest

from app import create_app
from models import SiteSettings, User, db as _db, utcnow


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
        _db.session.add(SiteSettings(key="setup_complete", value="true"))
        setup_admin = User(
            first_name="Setup",
            last_name="Admin",
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
        first_name="Admin",
        last_name="User",
        email="admin@example.com",
        is_admin=True,
        email_verified_at=utcnow(),
    )
    user.set_password("adminpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


def _login(client, email, password):
    client.post("/login", data={"email": email, "password": password})


class TestApplyMailSettings:
    def test_reads_server_and_port_from_site_settings(self, app):
        from mailer import _apply_mail_settings
        with app.app_context():
            SiteSettings.set("mail_server", "smtp.test.com")
            SiteSettings.set("mail_port", "465")
            _apply_mail_settings()
            assert app.config["MAIL_SERVER"] == "smtp.test.com"
            assert app.config["MAIL_PORT"] == 465

    def test_suppresses_send_when_unconfigured(self, app):
        from mailer import _apply_mail_settings
        with app.app_context():
            SiteSettings.set("mail_server", "")
            _apply_mail_settings()
            assert app.config["MAIL_SUPPRESS_SEND"] is True

    def test_enables_send_when_configured(self, app):
        from mailer import _apply_mail_settings
        with app.app_context():
            SiteSettings.set("mail_server", "smtp.example.com")
            _apply_mail_settings()
            assert app.config["MAIL_SUPPRESS_SEND"] is False

    def test_handles_invalid_port_gracefully(self, app):
        from mailer import _apply_mail_settings
        with app.app_context():
            SiteSettings.set("mail_server", "smtp.example.com")
            SiteSettings.set("mail_port", "notanumber")
            _apply_mail_settings()
            assert app.config["MAIL_PORT"] == 587

    def test_send_verification_calls_apply_settings(self, app):
        from mailer import send_verification_email
        with app.app_context():
            user = User(first_name="Test", last_name="User", email="test@example.com", email_verified_at=utcnow())
            _db.session.add(user)
            _db.session.commit()
            with patch("mailer._apply_mail_settings") as mock_apply:
                with patch("app.mail"):
                    try:
                        send_verification_email(user, "faketoken")
                    except Exception:
                        pass
            assert mock_apply.called


class TestTestEmailRoute:
    def test_returns_error_when_mail_unconfigured(self, client, admin_user):
        _login(client, "admin@example.com", "adminpass123")
        SiteSettings.set("mail_server", "")
        response = client.post("/admin/settings/test-email", follow_redirects=False)
        assert response.status_code == 302
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        assert any("error" in cat for cat, _ in flashes)

    def test_sends_when_configured(self, client, admin_user, app):
        _login(client, "admin@example.com", "adminpass123")
        with app.app_context():
            SiteSettings.set("mail_server", "smtp.test.com")
            SiteSettings.set("contact_email", "admin@example.com")
            SiteSettings.set("mail_default_sender", "test@example.com")
        response = client.post("/admin/settings/test-email", follow_redirects=False)
        assert response.status_code == 302
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        assert any("success" in cat for cat, _ in flashes)
