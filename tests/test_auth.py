import secrets
from datetime import timedelta
from urllib.parse import urlparse

from models import EmailVerificationToken, PasswordResetToken, User, _hash_token, db, utcnow


def test_dashboard_redirects_when_not_authenticated(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_verified_user_can_login(client, regular_user):
    response = client.post(
        "/login",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_login_next_param_double_slash_blocked(client, regular_user):
    resp = client.post(
        "/login?next=//evil.com",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.com" not in resp.headers["Location"]


def test_login_next_param_backslash_blocked(client, regular_user):
    resp = client.post(
        "/login?next=\\evil.com",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # Backslash is stripped; "evil.com" becomes a relative path — confirm netloc is not evil.com
    assert urlparse(resp.headers["Location"]).netloc != "evil.com"


def test_login_next_param_double_slash_with_path_blocked(client, regular_user):
    resp = client.post(
        "/login?next=//evil.com/path",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.com" not in resp.headers["Location"]


def test_login_next_param_relative_path_allowed(client, regular_user):
    resp = client.post(
        "/login?next=/dashboard",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_login_next_param_relative_path_with_slug_allowed(client, regular_user):
    resp = client.post(
        "/login?next=/events/my-event",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/events/my-event")


def test_wrong_password_rejected(client, regular_user):
    response = client.post(
        "/login",
        data={"email": "user@example.com", "password": "wrongpassword"},
        follow_redirects=True,
    )
    assert b"Invalid email or password" in response.data


def test_honeypot_rejection(client):
    response = client.post(
        "/register",
        data={
            "name": "Bot",
            "email": "bot@example.com",
            "password": "password123",
            "confirm_password": "password123",
            "website": "http://spam.com",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert User.query.filter_by(email="bot@example.com").first() is None


def test_new_registration_is_unverified(client):
    client.post(
        "/register",
        data={
            "name": "New User",
            "email": "newuser@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    user = User.query.filter_by(email="newuser@example.com").first()
    assert user is not None
    assert user.email_verified_at is None


def test_password_reset_token_expires(regular_user):
    record = PasswordResetToken(
        user_id=regular_user.id,
        token_hash="fakehash",
        expires_at=utcnow() - timedelta(hours=2),
    )
    db.session.add(record)
    db.session.commit()
    assert not record.is_valid


def test_password_reset_token_cannot_be_reused(client, regular_user):
    user_id = regular_user.id
    raw = secrets.token_urlsafe(32)

    record = PasswordResetToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=utcnow() + timedelta(hours=1),
    )
    db.session.add(record)
    db.session.commit()

    client.post(
        f"/reset-password/{raw}",
        data={"password": "newpassword123", "confirm_password": "newpassword123"},
    )

    used = PasswordResetToken.query.filter_by(token_hash=_hash_token(raw)).first()
    assert used is not None
    assert used.used_at is not None

    response = client.post(
        f"/reset-password/{raw}",
        data={"password": "anotherpassword123", "confirm_password": "anotherpassword123"},
        follow_redirects=True,
    )
    assert b"invalid or has expired" in response.data


def test_email_verification_sets_verified_at(client):
    user = User(name="Verify Me", email="verify@example.com", email_verified_at=None)
    user.set_password("password123")
    db.session.add(user)
    db.session.flush()
    raw_token = EmailVerificationToken.create_for_user(user)
    db.session.commit()

    assert user.email_verified_at is None

    response = client.get(f"/verify-email/{raw_token}", follow_redirects=False)
    assert response.status_code == 302

    db.session.refresh(user)
    assert user.email_verified_at is not None


def test_duplicate_email_registration_rejected(client):
    client.post(
        "/register",
        data={
            "name": "First User",
            "email": "duplicate@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert User.query.filter_by(email="duplicate@example.com").count() == 1

    response = client.post(
        "/register",
        data={
            "name": "Second User",
            "email": "duplicate@example.com",
            "password": "password456",
            "confirm_password": "password456",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"already exists" in response.data
    assert User.query.filter_by(email="duplicate@example.com").count() == 1
