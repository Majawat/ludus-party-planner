"""Tests for WebAuthn / Passkeys routes."""
import json
from unittest.mock import MagicMock, patch

import pytest

from models import SiteSettings, User, UserPlatformAccount, WebAuthnCredential, db as _db, utcnow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, user, password):
    return client.post(
        "/login",
        data={"email": user.email, "password": password},
        follow_redirects=True,
    )


def _enable_passkeys(app):
    with app.app_context():
        SiteSettings.set("passkeys_enabled", "true")


def _make_reg_verification():
    """Mock VerifiedRegistration returned by verify_registration_response."""
    v = MagicMock()
    v.credential_id = b"fakecredid"
    v.credential_public_key = b"fakepubkey"
    v.sign_count = 0
    v.aaguid = None
    return v


def _make_auth_verification():
    """Mock VerifiedAuthentication returned by verify_authentication_response."""
    v = MagicMock()
    v.new_sign_count = 1
    return v


def _make_reg_options():
    """Mock registration options object."""
    opts = MagicMock()
    opts.challenge = b"testchallenge123"
    return opts


def _make_auth_options():
    """Mock authentication options object."""
    opts = MagicMock()
    opts.challenge = b"authtestchallenge"
    return opts


def _insert_credential(app, user, credential_id="dGVzdGNyZWRpZA", public_key="dGVzdHB1YmtleQ",
                        device_name="Test Device"):
    """Insert a WebAuthnCredential for the given user and return it."""
    with app.app_context():
        cred = WebAuthnCredential(
            user_id=user.id,
            credential_id=credential_id,
            public_key=public_key,
            sign_count=0,
            device_name=device_name,
        )
        _db.session.add(cred)
        _db.session.commit()
        return cred.id


# ---------------------------------------------------------------------------
# Registration begin
# ---------------------------------------------------------------------------

class TestPasskeyRegisterBegin:
    def test_register_begin_returns_options_json(self, app, client, regular_user):
        _enable_passkeys(app)
        _login(client, regular_user, "userpass123")
        mock_opts = _make_reg_options()
        with patch("routes.auth.generate_registration_options", return_value=mock_opts), \
             patch("routes.auth.options_to_json", return_value='{"challenge":"dGVzdGNoYWxsZW5nZTEyMw"}'):
            resp = client.get("/auth/passkey/register/begin")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")
        data = json.loads(resp.data)
        assert "challenge" in data
        with client.session_transaction() as sess:
            assert "webauthn_register_challenge" in sess

    def test_register_begin_requires_login(self, app, client):
        _enable_passkeys(app)
        resp = client.get("/auth/passkey/register/begin")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_register_begin_404_when_disabled(self, app, client, regular_user):
        _login(client, regular_user, "userpass123")
        resp = client.get("/auth/passkey/register/begin")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Registration complete
# ---------------------------------------------------------------------------

class TestPasskeyRegisterComplete:
    def test_register_complete_stores_credential(self, app, client, regular_user):
        _enable_passkeys(app)
        _login(client, regular_user, "userpass123")
        # Set the challenge in the session
        with client.session_transaction() as sess:
            sess["webauthn_register_challenge"] = b"testchallenge123".hex()

        mock_ver = _make_reg_verification()
        with patch("routes.auth.verify_registration_response", return_value=mock_ver), \
             patch("routes.auth.bytes_to_base64url", side_effect=lambda b: b.decode() if isinstance(b, bytes) else b):
            resp = client.post(
                "/auth/passkey/register/complete",
                data=json.dumps({"id": "abc", "rawId": "abc", "type": "public-key",
                                 "device_name": "My Key",
                                 "response": {"clientDataJSON": "x", "attestationObject": "y"}}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("ok") is True
        with app.app_context():
            assert WebAuthnCredential.query.filter_by(user_id=regular_user.id).count() == 1

    def test_register_complete_rejects_missing_challenge(self, app, client, regular_user):
        _enable_passkeys(app)
        _login(client, regular_user, "userpass123")
        # No challenge set in session
        resp = client.post(
            "/auth/passkey/register/complete",
            data=json.dumps({"id": "abc", "rawId": "abc", "type": "public-key",
                             "response": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_register_complete_rejects_bad_response(self, app, client, regular_user):
        _enable_passkeys(app)
        _login(client, regular_user, "userpass123")
        with client.session_transaction() as sess:
            sess["webauthn_register_challenge"] = b"testchallenge123".hex()

        with patch("routes.auth.verify_registration_response", side_effect=Exception("invalid credential")):
            resp = client.post(
                "/auth/passkey/register/complete",
                data=json.dumps({"id": "abc", "rawId": "abc", "type": "public-key",
                                 "response": {}}),
                content_type="application/json",
            )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data


# ---------------------------------------------------------------------------
# Login begin
# ---------------------------------------------------------------------------

class TestPasskeyLoginBegin:
    def test_login_begin_returns_options_json(self, app, client):
        _enable_passkeys(app)
        mock_opts = _make_auth_options()
        with patch("routes.auth.generate_authentication_options", return_value=mock_opts), \
             patch("routes.auth.options_to_json", return_value='{"challenge":"YXV0aHRlc3RjaGFsbGVuZ2U"}'):
            resp = client.get("/auth/passkey/login/begin")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")
        data = json.loads(resp.data)
        assert "challenge" in data
        with client.session_transaction() as sess:
            assert "webauthn_auth_challenge" in sess

    def test_login_begin_404_when_disabled(self, app, client):
        resp = client.get("/auth/passkey/login/begin")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Login complete
# ---------------------------------------------------------------------------

class TestPasskeyLoginComplete:
    def test_login_complete_logs_in_user(self, app, client, regular_user):
        _enable_passkeys(app)
        cred_id = _insert_credential(app, regular_user, credential_id="mycredid123")
        with client.session_transaction() as sess:
            sess["webauthn_auth_challenge"] = b"authtestchallenge".hex()

        mock_ver = _make_auth_verification()
        with patch("routes.auth.verify_authentication_response", return_value=mock_ver), \
             patch("routes.auth.base64url_to_bytes", return_value=b"pubkeydata"):
            resp = client.post(
                "/auth/passkey/login/complete",
                data=json.dumps({"id": "mycredid123", "rawId": "mycredid123",
                                 "type": "public-key",
                                 "response": {"clientDataJSON": "x", "authenticatorData": "y",
                                              "signature": "z", "userHandle": None}}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("ok") is True
        assert "redirect" in data
        # Verify DB state updated
        with app.app_context():
            cred = WebAuthnCredential.query.get(cred_id)
            assert cred.sign_count == 1
            assert cred.last_used_at is not None

    def test_login_complete_rejects_unknown_credential(self, app, client):
        _enable_passkeys(app)
        with client.session_transaction() as sess:
            sess["webauthn_auth_challenge"] = b"authtestchallenge".hex()
        resp = client.post(
            "/auth/passkey/login/complete",
            data=json.dumps({"id": "doesnotexist", "rawId": "doesnotexist",
                             "type": "public-key",
                             "response": {"clientDataJSON": "x", "authenticatorData": "y",
                                          "signature": "z", "userHandle": None}}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_login_complete_rejects_bad_assertion(self, app, client, regular_user):
        _enable_passkeys(app)
        _insert_credential(app, regular_user, credential_id="mycredid456")
        with client.session_transaction() as sess:
            sess["webauthn_auth_challenge"] = b"authtestchallenge".hex()

        with patch("routes.auth.verify_authentication_response", side_effect=Exception("bad sig")), \
             patch("routes.auth.base64url_to_bytes", return_value=b"pubkeydata"):
            resp = client.post(
                "/auth/passkey/login/complete",
                data=json.dumps({"id": "mycredid456", "rawId": "mycredid456",
                                 "type": "public-key",
                                 "response": {"clientDataJSON": "x", "authenticatorData": "y",
                                              "signature": "z", "userHandle": None}}),
                content_type="application/json",
            )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_login_complete_rejects_missing_challenge(self, app, client, regular_user):
        _enable_passkeys(app)
        _insert_credential(app, regular_user, credential_id="mycredid789")
        # No challenge in session
        resp = client.post(
            "/auth/passkey/login/complete",
            data=json.dumps({"id": "mycredid789", "rawId": "mycredid789",
                             "type": "public-key",
                             "response": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data


# ---------------------------------------------------------------------------
# Remove passkey
# ---------------------------------------------------------------------------

class TestPasskeyRemove:
    def test_remove_passkey_succeeds(self, app, client, regular_user, admin_user):
        _enable_passkeys(app)
        # User has a password and two credentials
        cred1_id = _insert_credential(app, regular_user, credential_id="cred-remove-1")
        _insert_credential(app, regular_user, credential_id="cred-remove-2")
        _login(client, regular_user, "userpass123")
        resp = client.post(
            f"/auth/passkey/remove/{cred1_id}",
            data={"csrf_token": "test"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        with app.app_context():
            assert WebAuthnCredential.query.filter_by(
                user_id=regular_user.id, id=cred1_id
            ).first() is None
            # Second credential still exists
            assert WebAuthnCredential.query.filter_by(user_id=regular_user.id).count() == 1

    def test_remove_passkey_blocked_if_last_and_no_password(self, app, client):
        _enable_passkeys(app)
        # Create a user with no password and one passkey
        with app.app_context():
            no_pw_user = User(
                name="NoPw",
                email="nopw@example.com",
                email_verified_at=utcnow(),
            )
            _db.session.add(no_pw_user)
            _db.session.commit()
            cred = WebAuthnCredential(
                user_id=no_pw_user.id,
                credential_id="sole-cred",
                public_key="pubkey",
                sign_count=0,
            )
            _db.session.add(cred)
            _db.session.commit()
            cred_id = cred.id
            user_id = no_pw_user.id

        # Log in as this user by manipulating the session
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True

        resp = client.post(
            f"/auth/passkey/remove/{cred_id}",
            data={"csrf_token": "test"},
            follow_redirects=True,
        )
        # Should redirect back to profile with an error flash, credential still exists
        assert resp.status_code == 200
        assert b"must set a password" in resp.data
        with app.app_context():
            assert WebAuthnCredential.query.get(cred_id) is not None

    def test_remove_passkey_rejects_wrong_user(self, app, client, regular_user, admin_user):
        _enable_passkeys(app)
        # admin_user owns this credential
        cred_id = _insert_credential(app, admin_user, credential_id="admin-cred-1")
        # regular_user tries to remove it
        _login(client, regular_user, "userpass123")
        resp = client.post(
            f"/auth/passkey/remove/{cred_id}",
            data={"csrf_token": "test"},
        )
        assert resp.status_code == 403
        with app.app_context():
            assert WebAuthnCredential.query.get(cred_id) is not None
