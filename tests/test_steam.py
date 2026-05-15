"""Tests for Steam OpenID login and account management."""
from unittest.mock import MagicMock, patch

import pytest

from models import SiteSettings, User, UserPlatformAccount, db as _db, utcnow

STEAM_ID = "76561198000000001"
STEAM_IDENTITY_URL = f"https://steamcommunity.com/openid/id/{STEAM_ID}"
STEAM_OPENID_URL = "https://steamcommunity.com/openid"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def steam_settings(app):
    """Seed site_settings so Steam login is enabled."""
    _db.session.add(SiteSettings(key="steam_enabled", value="true"))
    _db.session.add(SiteSettings(key="steam_api_key", value=""))
    _db.session.commit()


@pytest.fixture()
def steam_user(app):
    """A user whose only login method is a Steam account (no password)."""
    user = User(
        name="Steam Player",
        email="steamplayer@example.com",
        email_verified_at=utcnow(),
    )
    _db.session.add(user)
    _db.session.flush()
    acct = UserPlatformAccount(
        user_id=user.id,
        platform="steam",
        username="SteamPlayer",
        platform_user_id=STEAM_ID,
    )
    _db.session.add(acct)
    _db.session.commit()
    return user


def _login(client, user, password):
    return client.post(
        "/login",
        data={"email": user.email, "password": password},
        follow_redirects=True,
    )


def _make_success_consumer(identity_url=STEAM_IDENTITY_URL):
    """Build a mock python3-openid Consumer that returns a SUCCESS response."""
    mock_response = MagicMock()
    mock_response.status = "success"  # SUCCESS constant is just the string "success"
    mock_response.identity_url = identity_url

    mock_auth_request = MagicMock()
    mock_auth_request.redirectURL.return_value = "https://steamcommunity.com/openid/login?fake=1"

    mock_consumer_instance = MagicMock()
    mock_consumer_instance.begin.return_value = mock_auth_request
    mock_consumer_instance.complete.return_value = mock_response

    mock_consumer_class = MagicMock(return_value=mock_consumer_instance)
    return mock_consumer_class


def _make_failure_consumer():
    """Build a mock Consumer that returns a non-SUCCESS response."""
    mock_response = MagicMock()
    mock_response.status = "failure"

    mock_consumer_instance = MagicMock()
    mock_consumer_instance.complete.return_value = mock_response

    mock_consumer_class = MagicMock(return_value=mock_consumer_instance)
    return mock_consumer_class


# ---------------------------------------------------------------------------
# /auth/steam/login
# ---------------------------------------------------------------------------

class TestSteamLogin:
    def test_returns_404_when_disabled(self, client):
        resp = client.get("/auth/steam/login")
        assert resp.status_code == 404

    def test_redirects_to_steam_when_enabled(self, client, steam_settings):
        mock_consumer = _make_success_consumer()
        with patch("routes.auth.Consumer", mock_consumer):
            resp = client.get("/auth/steam/login")
        assert resp.status_code == 302
        assert "steamcommunity.com" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# /auth/steam/callback
# ---------------------------------------------------------------------------

class TestSteamCallback:
    def test_known_steam_id_logs_in_user(self, client, steam_settings, steam_user):
        mock_consumer = _make_success_consumer()
        with patch("routes.auth.Consumer", mock_consumer):
            resp = client.get("/auth/steam/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/dashboard")

    def test_unknown_steam_id_redirects_to_complete_registration(self, client, steam_settings):
        mock_consumer = _make_success_consumer(
            identity_url="https://steamcommunity.com/openid/id/99999999999"
        )
        with patch("routes.auth.Consumer", mock_consumer):
            with client.session_transaction() as sess:
                pass  # ensure session exists
            resp = client.get("/auth/steam/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert "complete-registration" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert "steam_pending" in sess
            assert sess["steam_pending"]["steam64_id"] == "99999999999"

    def test_invalid_openid_response_flashes_error(self, client, steam_settings):
        mock_consumer = _make_failure_consumer()
        with patch("routes.auth.Consumer", mock_consumer):
            resp = client.get("/auth/steam/callback", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Steam login failed" in resp.data

    def test_connecting_links_steam_to_logged_in_user(self, client, steam_settings, regular_user):
        _login(client, regular_user, "userpass123")
        with client.session_transaction() as sess:
            sess["steam_connecting"] = True
        new_steam_id = "76561198000000099"
        mock_consumer = _make_success_consumer(
            identity_url=f"https://steamcommunity.com/openid/id/{new_steam_id}"
        )
        with patch("routes.auth.Consumer", mock_consumer):
            resp = client.get("/auth/steam/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/account")
        acct = UserPlatformAccount.query.filter_by(
            platform="steam", platform_user_id=new_steam_id
        ).first()
        assert acct is not None
        assert acct.user_id == regular_user.id

    def test_connecting_rejects_already_linked_steam_id(self, client, steam_settings, steam_user, regular_user):
        """Steam ID already linked to steam_user — should not link to regular_user."""
        _login(client, regular_user, "userpass123")
        with client.session_transaction() as sess:
            sess["steam_connecting"] = True
        mock_consumer = _make_success_consumer()  # returns STEAM_ID which belongs to steam_user
        with patch("routes.auth.Consumer", mock_consumer):
            resp = client.get("/auth/steam/callback", follow_redirects=True)
        assert resp.status_code == 200
        assert b"already linked to a different" in resp.data


# ---------------------------------------------------------------------------
# /auth/steam/complete-registration
# ---------------------------------------------------------------------------

class TestSteamCompleteRegistration:
    def test_get_without_session_redirects_to_login(self, client, steam_settings):
        resp = client.get("/auth/steam/complete-registration", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")

    def test_get_with_session_returns_200(self, client, steam_settings):
        with client.session_transaction() as sess:
            sess["steam_pending"] = {"steam64_id": STEAM_ID, "persona_name": "TestPlayer"}
        resp = client.get("/auth/steam/complete-registration")
        assert resp.status_code == 200
        assert b"TestPlayer" in resp.data

    def test_post_valid_creates_user_and_logs_in(self, client, steam_settings):
        with client.session_transaction() as sess:
            sess["steam_pending"] = {"steam64_id": STEAM_ID, "persona_name": "TestPlayer"}
        resp = client.post(
            "/auth/steam/complete-registration",
            data={
                "name": "Test Player",
                "email": "newsteamuser@example.com",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/dashboard")
        user = User.query.filter_by(email="newsteamuser@example.com").first()
        assert user is not None
        assert user.is_verified
        acct = UserPlatformAccount.query.filter_by(
            platform="steam", platform_user_id=STEAM_ID
        ).first()
        assert acct is not None
        assert acct.user_id == user.id

    def test_post_duplicate_email_shows_error(self, client, steam_settings, regular_user):
        with client.session_transaction() as sess:
            sess["steam_pending"] = {"steam64_id": STEAM_ID, "persona_name": "TestPlayer"}
        resp = client.post(
            "/auth/steam/complete-registration",
            data={
                "name": "Test Player",
                "email": regular_user.email,
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"already exists" in resp.data
        assert User.query.filter_by(email=regular_user.email).count() == 1

    def test_post_mismatched_passwords_shows_error(self, client, steam_settings):
        with client.session_transaction() as sess:
            sess["steam_pending"] = {"steam64_id": STEAM_ID, "persona_name": "TestPlayer"}
        resp = client.post(
            "/auth/steam/complete-registration",
            data={
                "name": "Test Player",
                "email": "another@example.com",
                "password": "password123",
                "confirm_password": "different456",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert User.query.filter_by(email="another@example.com").first() is None

    def test_returns_404_when_steam_disabled(self, client):
        resp = client.get("/auth/steam/complete-registration")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /account/connect/steam
# ---------------------------------------------------------------------------

class TestSteamConnect:
    def test_requires_login(self, client, steam_settings):
        resp = client.post("/account/connect/steam", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_returns_404_when_steam_disabled(self, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.post("/account/connect/steam")
        assert resp.status_code == 404

    def test_sets_connecting_flag_and_redirects(self, client, steam_settings, regular_user):
        _login(client, regular_user, "userpass123")
        mock_consumer = _make_success_consumer()
        with patch("routes.auth.Consumer", mock_consumer):
            resp = client.post("/account/connect/steam", follow_redirects=False)
        assert resp.status_code == 302
        assert "steam" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("steam_connecting") is True


# ---------------------------------------------------------------------------
# /account/disconnect/steam
# ---------------------------------------------------------------------------

class TestSteamDisconnect:
    def test_requires_login(self, client, steam_settings):
        resp = client.post("/account/disconnect/steam", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_blocks_when_no_password_and_last_method(self, client, steam_settings, steam_user):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(steam_user.id)
            sess["_fresh"] = True
        resp = client.post("/account/disconnect/steam", follow_redirects=True)
        assert resp.status_code == 200
        assert b"must set a password" in resp.data
        assert UserPlatformAccount.query.filter_by(
            platform="steam", user_id=steam_user.id
        ).first() is not None

    def test_succeeds_when_user_has_password(self, client, steam_settings, regular_user):
        """regular_user has a password — linking and then disconnecting Steam should work."""
        acct = UserPlatformAccount(
            user_id=regular_user.id,
            platform="steam",
            username="RegularSteam",
            platform_user_id="76561198000000002",
        )
        _db.session.add(acct)
        _db.session.commit()
        _login(client, regular_user, "userpass123")
        resp = client.post("/account/disconnect/steam", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/account")
        assert UserPlatformAccount.query.filter_by(
            platform="steam", user_id=regular_user.id
        ).first() is None

    def test_no_op_when_not_connected(self, client, steam_settings, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.post("/account/disconnect/steam", follow_redirects=True)
        assert resp.status_code == 200
        assert b"No Steam account" in resp.data
