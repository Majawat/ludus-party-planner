"""Regression tests for the 2026-09 security review fixes:
- 2FA is enforced on OAuth and Steam login (not just password/passkey).
- OAuth/passkey-only users (no password) can still disable/regenerate 2FA.
- The registrations CSV export neutralizes spreadsheet formula injection.
"""
import csv
import io
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import flask
import pyotp
from werkzeug.security import generate_password_hash

from models import Registration, SiteSettings, User, UserPlatformAccount, db, utcnow


# ---------------------------------------------------------------------------
# 2FA enforced on social logins
# ---------------------------------------------------------------------------

def _discord_mock(provider_user_id, username, email):
    client = MagicMock()
    client.authorize_redirect.return_value = flask.redirect("https://discord.example/authorize")
    client.authorize_access_token.return_value = {"access_token": "fake-token"}
    resp = MagicMock()
    resp.json.return_value = {
        "id": provider_user_id,
        "username": username,
        "global_name": username,
        "email": email,
    }
    client.get.return_value = resp
    return client


def test_oauth_login_with_2fa_challenges_not_logs_in(client, oauth_user):
    """A 2FA-enabled user logging in via OAuth is sent to the 2FA challenge,
    not straight into the session (previously OAuth bypassed 2FA entirely)."""
    oauth_user.totp_secret = pyotp.random_base32()
    db.session.commit()

    mock_client = _discord_mock("999888777", "OAuthUser#1234", "oauth@example.com")
    with patch("routes.auth.get_oauth_client", return_value=mock_client):
        resp = client.get("/auth/discord/callback?code=fake&state=fake", follow_redirects=False)

    assert resp.status_code == 302
    assert "/auth/2fa/verify" in resp.headers["Location"]

    # Still not authenticated — dashboard bounces to login.
    dash = client.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 302
    assert "/login" in dash.headers["Location"]


def _steam_success_consumer(steam_id):
    resp = MagicMock()
    resp.status = "success"  # openid SUCCESS constant is the string "success"
    resp.identity_url = f"https://steamcommunity.com/openid/id/{steam_id}"
    instance = MagicMock()
    instance.complete.return_value = resp
    return MagicMock(return_value=instance)


def test_steam_login_with_2fa_challenges_not_logs_in(client, app):
    """A 2FA-enabled user logging in via Steam OpenID is sent to the 2FA challenge."""
    steam_id = "76561198000000001"
    SiteSettings.set("steam_enabled", "true")
    user = User(
        first_name="Steam",
        last_name="Player",
        email="steam2fa@example.com",
        email_verified_at=utcnow(),
        totp_secret=pyotp.random_base32(),
    )
    user.set_password("securepass123")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserPlatformAccount(
        user_id=user.id, platform="steam", username="SteamPlayer", platform_user_id=steam_id,
    ))
    db.session.commit()

    with patch("routes.auth.Consumer", _steam_success_consumer(steam_id)):
        resp = client.get("/auth/steam/callback", follow_redirects=False)

    assert resp.status_code == 302
    assert "/auth/2fa/verify" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Passwordless users can still turn 2FA off
# ---------------------------------------------------------------------------

def test_oauth_only_user_can_disable_2fa_without_password(client, oauth_user):
    """A user with no password (OAuth/passkey-only) can disable 2FA — requiring a
    password here previously locked them out permanently."""
    oauth_user.totp_secret = pyotp.random_base32()
    oauth_user.totp_backup_codes = json.dumps([generate_password_hash("AAAA1111")])
    db.session.commit()
    assert not oauth_user.has_password

    with client.session_transaction() as sess:
        sess["_user_id"] = str(oauth_user.id)
        sess["_fresh"] = True

    resp = client.post("/account/security/disable", data={}, follow_redirects=False)
    assert resp.status_code == 302

    refreshed = db.session.get(User, oauth_user.id)
    assert refreshed.totp_secret is None
    assert refreshed.totp_backup_codes is None


def test_password_user_still_needs_password_to_disable_2fa(client, app):
    """Users who DO have a password must still re-enter it to disable 2FA."""
    user = User(
        first_name="Pass",
        last_name="User",
        email="passuser@example.com",
        email_verified_at=utcnow(),
        totp_secret=pyotp.random_base32(),
    )
    user.set_password("securepass123")
    db.session.add(user)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True

    # Wrong/blank password → rejected, 2FA stays on.
    client.post("/account/security/disable", data={"password": "wrong"}, follow_redirects=False)
    assert db.session.get(User, user.id).totp_secret is not None


# ---------------------------------------------------------------------------
# CSV formula-injection neutralization
# ---------------------------------------------------------------------------

def test_csv_export_escapes_formula_injection(client, admin_user, published_event, ticket_type):
    """Attendee-controlled fields that look like spreadsheet formulas are prefixed
    with a single quote in the export."""
    user = User(
        first_name="=cmd|'/c calc'!A1",
        last_name="Normal",
        gamertag="=HYPERLINK('http://evil','x')",
        email="inject@example.com",
        email_verified_at=utcnow(),
    )
    user.set_password("securepass123")
    db.session.add(user)
    db.session.flush()
    db.session.add(Registration(
        user_id=user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    ))
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_user.id)
        sess["_fresh"] = True

    resp = client.get(f"/admin/events/{published_event.id}/registrations/export.csv")
    assert resp.status_code == 200

    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    injected = [r for r in rows[1:] if len(r) > 3 and r[3] == "inject@example.com"]
    assert injected, "injected registration row not found in export"
    row = injected[0]
    assert row[0].startswith("'="), f"first_name not neutralized: {row[0]!r}"
    assert row[2].startswith("'="), f"gamertag not neutralized: {row[2]!r}"
    # A benign value (email) is left untouched.
    assert row[3] == "inject@example.com"
