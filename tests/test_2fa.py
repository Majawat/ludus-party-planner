"""Tests for optional TOTP two-factor authentication (v1.4b)."""
import json
import time

import pyotp
import pytest
from werkzeug.security import generate_password_hash

from models import User, db, utcnow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def user_with_2fa(app):
    """A verified user with TOTP 2FA already enabled and 8 backup codes."""
    secret = pyotp.random_base32()
    raw_codes = ["AABB1122", "CCDD3344", "EEFF5566", "GGHH7788",
                 "IIJJ9900", "KKLL1234", "MMNN5678", "OOPPABCD"]
    hashed_codes = [generate_password_hash(c) for c in raw_codes]
    user = User(
        name="2FA User",
        email="twofauser@example.com",
        is_admin=False,
        email_verified_at=utcnow(),
        totp_secret=secret,
        totp_backup_codes=json.dumps(hashed_codes),
    )
    user.set_password("securepass123")
    db.session.add(user)
    db.session.commit()
    # Store raw codes on the fixture for test access
    user._raw_backup_codes = raw_codes
    return user


# ---------------------------------------------------------------------------
# Login flow tests
# ---------------------------------------------------------------------------

def test_login_with_2fa_redirects_to_challenge(client, user_with_2fa):
    """Correct password + 2FA enabled → redirect to 2FA challenge, not logged in."""
    resp = client.post(
        "/login",
        data={"email": "twofauser@example.com", "password": "securepass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/auth/2fa/verify" in resp.headers["Location"]

    # User should NOT be logged in yet
    dashboard = client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 302
    assert "/login" in dashboard.headers["Location"]


def test_login_without_2fa_logs_in_directly(client, regular_user):
    """User without 2FA set up is logged in directly after correct password."""
    resp = client.post(
        "/login",
        data={"email": "user@example.com", "password": "userpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_2fa_challenge_valid_code_logs_in(client, user_with_2fa):
    """Valid TOTP code on 2FA challenge completes login."""
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    totp = pyotp.TOTP(user_with_2fa.totp_secret)
    resp = client.post(
        "/auth/2fa/verify",
        data={"code": totp.now()},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    # Session keys should be cleaned up
    with client.session_transaction() as sess:
        assert "pending_2fa_user_id" not in sess
        assert "2fa_attempts" not in sess


def test_2fa_challenge_invalid_code_rejected(client, user_with_2fa):
    """Invalid TOTP code on 2FA challenge is rejected; user stays unauthenticated."""
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    resp = client.post(
        "/auth/2fa/verify",
        data={"code": "000000"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Invalid code" in resp.data

    # Still not logged in
    dashboard = client.get("/dashboard", follow_redirects=False)
    assert "/login" in dashboard.headers["Location"]


def test_2fa_challenge_too_many_attempts_locks_out(client, user_with_2fa):
    """After 5 invalid attempts the session is cleared and user is sent to login."""
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    for _ in range(5):
        client.post("/auth/2fa/verify", data={"code": "000000"})

    resp = client.post(
        "/auth/2fa/verify",
        data={"code": "000000"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    with client.session_transaction() as sess:
        assert "pending_2fa_user_id" not in sess
        assert "2fa_attempts" not in sess


def test_2fa_backup_code_valid_logs_in(client, user_with_2fa):
    """Valid backup code logs in and removes the code from the DB."""
    raw_code = user_with_2fa._raw_backup_codes[0]
    original_codes = json.loads(user_with_2fa.totp_backup_codes)

    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    resp = client.post(
        "/auth/2fa/verify",
        data={"code": raw_code, "use_backup": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    db.session.refresh(user_with_2fa)
    remaining = json.loads(user_with_2fa.totp_backup_codes)
    assert len(remaining) == len(original_codes) - 1


def test_2fa_backup_code_invalid_rejected(client, user_with_2fa):
    """Wrong backup code is rejected."""
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    resp = client.post(
        "/auth/2fa/verify",
        data={"code": "ZZZZZZZZ", "use_backup": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Invalid backup code" in resp.data


def test_2fa_verify_without_session_redirects_to_login(client):
    """GET /auth/2fa/verify with no pending session redirects to login."""
    resp = client.get("/auth/2fa/verify", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Setup flow tests
# ---------------------------------------------------------------------------

def _login(client, email, password):
    client.post("/login", data={"email": email, "password": password})


def _login_with_2fa(client, email, password, totp_secret):
    """Log in a user who has 2FA enabled by completing the TOTP challenge."""
    client.post("/login", data={"email": email, "password": password})
    totp = pyotp.TOTP(totp_secret)
    client.post("/auth/2fa/verify", data={"code": totp.now()})


def test_setup_generates_secret_in_session_not_db(client, regular_user):
    """GET /account/security/setup stores secret in session, not in DB."""
    _login(client, "user@example.com", "userpass123")

    client.get("/account/security/setup")

    with client.session_transaction() as sess:
        assert "totp_setup_secret" in sess

    db.session.refresh(regular_user)
    assert regular_user.totp_secret is None


def test_verify_setup_valid_code_saves_secret(client, regular_user):
    """Valid TOTP code on setup saves totp_secret and 8 backup codes to DB."""
    _login(client, "user@example.com", "userpass123")

    import pyotp as _pyotp
    secret = _pyotp.random_base32()
    with client.session_transaction() as sess:
        sess["totp_setup_secret"] = secret

    totp = _pyotp.TOTP(secret)
    resp = client.post(
        "/account/security/verify-setup",
        data={"code": totp.now()},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.session.refresh(regular_user)
    assert regular_user.totp_secret == secret
    assert regular_user.totp_backup_codes is not None
    codes = json.loads(regular_user.totp_backup_codes)
    assert len(codes) == 8


def test_verify_setup_invalid_code_rejected(client, regular_user):
    """Invalid code during setup does not save secret."""
    _login(client, "user@example.com", "userpass123")

    import pyotp as _pyotp
    secret = _pyotp.random_base32()
    with client.session_transaction() as sess:
        sess["totp_setup_secret"] = secret

    resp = client.post(
        "/account/security/verify-setup",
        data={"code": "000000"},
        follow_redirects=False,
    )
    # Invalid code renders the setup page directly (200) rather than redirecting,
    # so the user sees the same QR code and can try again without a secret rotation.
    assert resp.status_code == 200

    db.session.refresh(regular_user)
    assert regular_user.totp_secret is None


def test_verify_setup_without_session_redirects(client, regular_user):
    """POST to verify-setup without session secret redirects to setup page."""
    _login(client, "user@example.com", "userpass123")

    resp = client.post(
        "/account/security/verify-setup",
        data={"code": "123456"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/security/setup" in resp.headers["Location"]


def test_backup_codes_display_shown_once(client, regular_user):
    """Backup codes are shown once and cleared from session on first GET."""
    _login(client, "user@example.com", "userpass123")

    raw_codes = ["AABB1122", "CCDD3344"]
    with client.session_transaction() as sess:
        sess["totp_backup_codes_display"] = raw_codes

    resp = client.get("/account/security/backup-codes-display")
    assert resp.status_code == 200
    assert b"AABB1122" in resp.data

    with client.session_transaction() as sess:
        assert "totp_backup_codes_display" not in sess

    # Second GET redirects since session key is gone
    resp2 = client.get("/account/security/backup-codes-display", follow_redirects=False)
    assert resp2.status_code == 302
    assert "/security" in resp2.headers["Location"]


def test_backup_codes_display_without_session_redirects(client, regular_user):
    """GET backup-codes-display without session key redirects to security page."""
    _login(client, "user@example.com", "userpass123")

    resp = client.get("/account/security/backup-codes-display", follow_redirects=False)
    assert resp.status_code == 302
    assert "/security" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Disable 2FA tests
# ---------------------------------------------------------------------------

def test_disable_2fa_requires_correct_password(client, user_with_2fa):
    """Wrong password does not disable 2FA."""
    _login_with_2fa(client, "twofauser@example.com", "securepass123", user_with_2fa.totp_secret)

    original_secret = user_with_2fa.totp_secret
    resp = client.post(
        "/account/security/disable",
        data={"password": "wrongpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/security" in resp.headers["Location"]

    db.session.refresh(user_with_2fa)
    assert user_with_2fa.totp_secret == original_secret


def test_disable_2fa_clears_secret_and_codes(client, user_with_2fa):
    """Correct password clears totp_secret and totp_backup_codes."""
    _login_with_2fa(client, "twofauser@example.com", "securepass123", user_with_2fa.totp_secret)

    resp = client.post(
        "/account/security/disable",
        data={"password": "securepass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.session.refresh(user_with_2fa)
    assert user_with_2fa.totp_secret is None
    assert user_with_2fa.totp_backup_codes is None


# ---------------------------------------------------------------------------
# Regenerate backup codes tests
# ---------------------------------------------------------------------------

def test_regenerate_requires_password(client, user_with_2fa):
    """Wrong password does not regenerate backup codes."""
    _login_with_2fa(client, "twofauser@example.com", "securepass123", user_with_2fa.totp_secret)
    original_codes = user_with_2fa.totp_backup_codes

    resp = client.post(
        "/account/security/regenerate-backup-codes",
        data={"password": "wrongpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.session.refresh(user_with_2fa)
    assert user_with_2fa.totp_backup_codes == original_codes


def test_regenerate_produces_new_codes(client, user_with_2fa):
    """Correct password generates a new set of backup codes."""
    _login_with_2fa(client, "twofauser@example.com", "securepass123", user_with_2fa.totp_secret)
    original_codes = user_with_2fa.totp_backup_codes

    resp = client.post(
        "/account/security/regenerate-backup-codes",
        data={"password": "securepass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/backup-codes-display" in resp.headers["Location"]

    db.session.refresh(user_with_2fa)
    assert user_with_2fa.totp_backup_codes != original_codes
    assert len(json.loads(user_with_2fa.totp_backup_codes)) == 8

    with client.session_transaction() as sess:
        assert "totp_backup_codes_display" in sess
        assert len(sess["totp_backup_codes_display"]) == 8


# ---------------------------------------------------------------------------
# Security / edge case tests
# ---------------------------------------------------------------------------

def test_verify_uses_sliding_window(app):
    """verify_totp_code accepts a code from the previous 30-second window (valid_window=1)."""
    from totp import verify_totp_code
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    # Generate a code for 31 seconds ago (previous window)
    prev_code = totp.at(time.time() - 31)
    with app.app_context():
        assert verify_totp_code(secret, prev_code) is True


def test_backup_code_is_single_use(client, user_with_2fa):
    """A backup code that has been used once cannot be used again."""
    raw_code = user_with_2fa._raw_backup_codes[0]

    # First use — logs in successfully
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    resp = client.post(
        "/auth/2fa/verify",
        data={"code": raw_code, "use_backup": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    # Log out, then attempt same code again
    client.post("/logout")
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    resp2 = client.post(
        "/auth/2fa/verify",
        data={"code": raw_code, "use_backup": "1"},
        follow_redirects=True,
    )
    assert resp2.status_code == 200
    assert b"Invalid backup code" in resp2.data

    db.session.refresh(user_with_2fa)
    remaining = json.loads(user_with_2fa.totp_backup_codes)
    # Code should not appear in remaining (already consumed in first use)
    from werkzeug.security import check_password_hash
    for hashed in remaining:
        assert not check_password_hash(hashed, raw_code)


def test_setup_reuses_secret_on_retry(client, regular_user):
    """GET /account/security/setup twice reuses the same session secret rather than generating a new one."""
    _login(client, "user@example.com", "userpass123")

    client.get("/account/security/setup")
    with client.session_transaction() as sess:
        secret_first = sess.get("totp_setup_secret")

    client.get("/account/security/setup")
    with client.session_transaction() as sess:
        secret_second = sess.get("totp_setup_secret")

    assert secret_first is not None
    assert secret_first == secret_second


def test_2fa_attempts_cleared_on_new_login(client, user_with_2fa):
    """Stale 2fa_attempts from a previous session don't carry over to a fresh login challenge."""
    # Fail the 2FA challenge 3 times in one "session"
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = user_with_2fa.id
        sess["pending_2fa_remember"] = False

    for _ in range(3):
        client.post("/auth/2fa/verify", data={"code": "000000"})

    # Log out (clears 2FA state)
    client.post("/logout")

    # Start a fresh login challenge — should reset the attempt counter
    resp = client.post(
        "/login",
        data={"email": "twofauser@example.com", "password": "securepass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/auth/2fa/verify" in resp.headers["Location"]

    # One more bad code — should NOT trigger lockout (counter was reset)
    resp = client.post("/auth/2fa/verify", data={"code": "000000"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid code" in resp.data


def test_next_param_preserved_through_2fa(client, user_with_2fa):
    """A ?next= param on login is preserved through the 2FA challenge and honoured on success."""
    resp = client.post(
        "/login?next=/account",
        data={"email": "twofauser@example.com", "password": "securepass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/auth/2fa/verify" in resp.headers["Location"]

    totp = pyotp.TOTP(user_with_2fa.totp_secret)
    resp2 = client.post(
        "/auth/2fa/verify",
        data={"code": totp.now()},
        follow_redirects=False,
    )
    assert resp2.status_code == 302
    assert "/account" in resp2.headers["Location"]


def test_logout_clears_2fa_session_state(client, regular_user):
    """Logging out clears all pending 2FA session keys."""
    # Log in as a normal user (no 2FA), inject stale 2FA state, then log out.
    _login(client, "user@example.com", "userpass123")
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = 99
        sess["pending_2fa_remember"] = True
        sess["pending_2fa_next"] = "/account"
        sess["2fa_attempts"] = 3

    client.post("/logout")

    with client.session_transaction() as sess:
        assert "pending_2fa_user_id" not in sess
        assert "pending_2fa_remember" not in sess
        assert "pending_2fa_next" not in sess
        assert "2fa_attempts" not in sess
