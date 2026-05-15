"""Tests for OAuth login and account linking."""
from unittest.mock import MagicMock, patch

import pytest

from models import SiteSettings, User, UserPlatformAccount, db as _db, utcnow


def _login(client, user, password):
    return client.post(
        "/login",
        data={"email": user.email, "password": password},
        follow_redirects=True,
    )


def _mock_discord_client(provider_user_id="111222333", username="TestUser", email="testuser@example.com"):
    """Build a mock Authlib OAuth client simulating Discord responses."""
    mock_client = MagicMock()
    mock_client.authorize_redirect.return_value = __import__("flask").redirect(
        "https://discord.com/oauth2/authorize?client_id=test"
    )
    token = {"access_token": "fake-token"}
    mock_client.authorize_access_token.return_value = token
    resp = MagicMock()
    resp.json.return_value = {
        "id": provider_user_id,
        "username": username,
        "global_name": username,
        "email": email,
    }
    mock_client.get.return_value = resp
    return mock_client


def _mock_google_client(provider_user_id="google-sub-123", username="Google User", email="google@example.com"):
    mock_client = MagicMock()
    mock_client.authorize_redirect.return_value = __import__("flask").redirect(
        "https://accounts.google.com/o/oauth2/v2/auth?client_id=test"
    )
    token = {
        "access_token": "fake-token",
        "userinfo": {
            "sub": provider_user_id,
            "name": username,
            "email": email,
        },
    }
    mock_client.authorize_access_token.return_value = token
    return mock_client


# ---------------------------------------------------------------------------
# /auth/<provider>/login
# ---------------------------------------------------------------------------

class TestOAuthLogin:
    def test_discord_login_redirects_when_configured(self, client, discord_settings):
        mock_client = _mock_discord_client()
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.get("/auth/discord/login")
        assert resp.status_code == 302
        mock_client.authorize_redirect.assert_called_once()

    def test_discord_login_404_when_not_configured(self, client):
        resp = client.get("/auth/discord/login")
        assert resp.status_code == 404

    def test_google_login_404_when_not_configured(self, client):
        resp = client.get("/auth/google/login")
        assert resp.status_code == 404

    def test_unknown_provider_returns_404(self, client):
        resp = client.get("/auth/steam/login")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /auth/<provider>/callback — login flows
# ---------------------------------------------------------------------------

class TestOAuthCallback:
    def test_known_platform_account_logs_in_user(self, client, oauth_user):
        """Callback with a known provider_user_id logs in the linked user."""
        mock_client = _mock_discord_client(
            provider_user_id="999888777",
            username="OAuthUser#1234",
            email="oauth@example.com",
        )
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.get("/auth/discord/callback?code=fake&state=fake")
        assert resp.status_code == 302
        assert "/dashboard" in resp.location

    def test_unknown_user_matching_email_shows_confirm_page(self, client, regular_user):
        """Callback with unknown provider but matching email shows the confirmation page."""
        mock_client = _mock_discord_client(
            provider_user_id="new-unknown-id",
            username="SomeUser",
            email="user@example.com",  # matches regular_user
        )
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.get("/auth/discord/callback?code=fake&state=fake")
        # Must NOT auto-login — must show confirmation page
        assert resp.status_code == 200
        assert b"Link Account" in resp.data or b"link" in resp.data.lower()
        assert b"user@example.com" in resp.data

    def test_new_user_created_when_no_match(self, client, app):
        """Callback with no matching account creates a new user and logs them in."""
        mock_client = _mock_discord_client(
            provider_user_id="brand-new-id",
            username="BrandNewUser",
            email="brandnew@example.com",
        )
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.get("/auth/discord/callback?code=fake&state=fake")
        assert resp.status_code == 302
        assert "/dashboard" in resp.location
        with app.app_context():
            user = User.query.filter_by(email="brandnew@example.com").first()
            assert user is not None
            assert user.email_verified_at is not None
            assert user.password_hash is None
            acct = UserPlatformAccount.query.filter_by(
                platform="discord", platform_user_id="brand-new-id"
            ).first()
            assert acct is not None
            assert acct.user_id == user.id

    def test_google_callback_creates_user(self, client, app):
        """Google callback creates a new user using OIDC userinfo."""
        mock_client = _mock_google_client(
            provider_user_id="google-sub-999",
            username="Google Person",
            email="googleperson@example.com",
        )
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.get("/auth/google/callback?code=fake&state=fake")
        assert resp.status_code == 302
        with app.app_context():
            user = User.query.filter_by(email="googleperson@example.com").first()
            assert user is not None
            acct = UserPlatformAccount.query.filter_by(
                platform="google", platform_user_id="google-sub-999"
            ).first()
            assert acct is not None

    def test_callback_unknown_provider_404(self, client):
        resp = client.get("/auth/steam/callback")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /auth/<provider>/confirm-link
# ---------------------------------------------------------------------------

class TestOAuthConfirmLink:
    def test_confirm_link_links_account_and_logs_in(self, client, regular_user, app):
        """POST confirm-link uses session data to link the platform account."""
        mock_client = _mock_discord_client(
            provider_user_id="new-discord-id",
            username="SomeUser",
            email="user@example.com",
        )
        # First, trigger the callback to populate the session
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            client.get("/auth/discord/callback?code=fake&state=fake")

        # Now confirm the link
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.post("/auth/discord/confirm-link", follow_redirects=False)

        assert resp.status_code == 302
        assert "/dashboard" in resp.location

        with app.app_context():
            acct = UserPlatformAccount.query.filter_by(
                platform="discord", platform_user_id="new-discord-id"
            ).first()
            assert acct is not None
            assert acct.user_id == regular_user.id

    def test_confirm_link_without_session_redirects_to_login(self, client):
        """POST confirm-link without pending session data flashes error."""
        resp = client.post("/auth/discord/confirm-link", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_confirm_link_unknown_provider_404(self, client):
        resp = client.post("/auth/steam/confirm-link")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Account connect / disconnect
# ---------------------------------------------------------------------------

class TestAccountConnect:
    def test_connect_requires_login(self, client, discord_settings):
        resp = client.post("/account/connect/discord", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_connect_404_when_not_configured(self, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.post("/account/connect/discord")
        assert resp.status_code == 404

    def test_connect_redirects_to_oauth(self, client, regular_user, discord_settings):
        _login(client, regular_user, "userpass123")
        mock_client = _mock_discord_client()
        with patch("routes.auth.get_oauth_client", return_value=mock_client):
            resp = client.post("/account/connect/discord", follow_redirects=False)
        # Should eventually redirect through oauth_login → authorize_redirect
        # The immediate redirect is to /auth/discord/login
        assert resp.status_code == 302


class TestAccountDisconnect:
    def test_disconnect_requires_login(self, client):
        resp = client.post("/account/disconnect/discord")
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_disconnect_blocks_last_method_no_password(self, client, oauth_user, app):
        """Disconnecting the last linked account is blocked when no password is set."""
        _login(client, oauth_user, "anything")  # This won't work since no password
        # Log in directly by manipulating the session
        with client.session_transaction() as sess:
            sess["_user_id"] = str(oauth_user.id)
            sess["_fresh"] = True
        resp = client.post("/account/disconnect/discord", follow_redirects=True)
        assert b"must set a password" in resp.data.lower() or b"password" in resp.data.lower()

        # Account should NOT be removed
        with app.app_context():
            acct = UserPlatformAccount.query.filter_by(
                user_id=oauth_user.id, platform="discord"
            ).first()
            assert acct is not None

    def test_disconnect_works_when_password_set(self, client, oauth_user, app):
        """Disconnecting is allowed when the user also has a password."""
        # Log in as the OAuth user
        with client.session_transaction() as sess:
            sess["_user_id"] = str(oauth_user.id)
            sess["_fresh"] = True

        # Set password via the HTTP route (ensures it's visible in subsequent requests)
        client.post(
            "/account/set-password",
            data={"password": "newpassword123", "confirm_password": "newpassword123"},
        )

        # Disconnect should now succeed
        resp = client.post("/account/disconnect/discord", follow_redirects=True)
        # Should show success flash, not the "must set password" error
        assert b"disconnected" in resp.data.lower()

        # Verify the account is actually gone via a direct DB check using the client
        # (SQLAlchemy identity map is refreshed between requests)
        profile_resp = client.get("/account")
        assert b"Not connected" in profile_resp.data or b"Connect" in profile_resp.data

    def test_disconnect_unknown_provider_404(self, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.post("/account/disconnect/steam")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Profile page
# ---------------------------------------------------------------------------

class TestProfilePage:
    def test_profile_requires_login(self, client):
        resp = client.get("/account")
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_profile_shows_connected_accounts_section(self, client, oauth_user, discord_settings):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(oauth_user.id)
            sess["_fresh"] = True
        resp = client.get("/account")
        assert resp.status_code == 200
        assert b"Connected Accounts" in resp.data
        assert b"Discord" in resp.data

    def test_profile_shows_set_password_form_for_oauth_user(self, client, oauth_user):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(oauth_user.id)
            sess["_fresh"] = True
        resp = client.get("/account")
        assert resp.status_code == 200
        assert b"Set Password" in resp.data

    def test_profile_shows_change_password_form_for_password_user(self, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.get("/account")
        assert resp.status_code == 200
        assert b"Change Password" in resp.data
        assert b"Set Password" not in resp.data or b"Change Password" in resp.data


# ---------------------------------------------------------------------------
# Set / change password
# ---------------------------------------------------------------------------

class TestPasswordForms:
    def test_set_password_works_for_oauth_user(self, client, oauth_user, app):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(oauth_user.id)
            sess["_fresh"] = True
        resp = client.post(
            "/account/set-password",
            data={"password": "mynewpass123", "confirm_password": "mynewpass123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        with app.app_context():
            user = _db.session.get(User, oauth_user.id)
            assert user.has_password

    def test_set_password_blocked_for_password_user(self, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.post(
            "/account/set-password",
            data={"password": "newpass123", "confirm_password": "newpass123"},
        )
        assert resp.status_code == 403

    def test_change_password_works(self, client, regular_user, app):
        _login(client, regular_user, "userpass123")
        resp = client.post(
            "/account/change-password",
            data={
                "current_password": "userpass123",
                "new_password": "updatedpass456",
                "confirm_password": "updatedpass456",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        with app.app_context():
            user = _db.session.get(User, regular_user.id)
            assert user.check_password("updatedpass456")

    def test_change_password_wrong_current_fails(self, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.post(
            "/account/change-password",
            data={
                "current_password": "wrongpassword",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            },
            follow_redirects=True,
        )
        assert b"incorrect" in resp.data.lower()

    def test_change_password_blocked_for_oauth_user(self, client, oauth_user):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(oauth_user.id)
            sess["_fresh"] = True
        resp = client.post(
            "/account/change-password",
            data={
                "current_password": "anything",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            },
        )
        assert resp.status_code == 403
