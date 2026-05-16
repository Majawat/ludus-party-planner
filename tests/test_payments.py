"""Tests for Stripe and PayPal payment integration."""
import json
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from models import Registration, SiteSettings, TicketType, db as _db, utcnow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _make_stripe_session(payment_status="paid", registration_id=None, status="open"):
    s = MagicMock()
    s.id = "cs_test_fake123"
    s.url = "https://checkout.stripe.com/pay/cs_test_fake123"
    s.status = status
    s.payment_status = payment_status
    s.metadata = {"registration_id": str(registration_id)} if registration_id else {}
    return s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def paid_ticket_type(app, published_event):
    tt = TicketType(
        event_id=published_event.id,
        name="Paid Pass",
        price=25.00,
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
def free_ticket_type(app, published_event):
    tt = TicketType(
        event_id=published_event.id,
        name="Free Pass",
        price=0.00,
        quantity_total=10,
        seatable=False,
        includes_lodging=False,
        valid_days=json.dumps(["2026-08-07"]),
        max_per_user=1,
        is_active=True,
    )
    _db.session.add(tt)
    _db.session.commit()
    return tt


@pytest.fixture()
def stripe_settings(app):
    SiteSettings.set("stripe_enabled", "true")
    SiteSettings.set("stripe_secret_key", "sk_test_fake")
    SiteSettings.set("stripe_webhook_secret", "whsec_fake")


@pytest.fixture()
def paypal_settings(app):
    SiteSettings.set("paypal_enabled", "true")
    SiteSettings.set("paypal_client_id", "fake_client_id")
    SiteSettings.set("paypal_client_secret", "fake_secret")
    SiteSettings.set("paypal_mode", "sandbox")
    SiteSettings.set("paypal_webhook_id", "fake_webhook_id")


@pytest.fixture()
def unpaid_stripe_registration(app, regular_user, published_event, paid_ticket_type):
    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=paid_ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        stripe_session_id="cs_test_fake123",
        payment_processor="stripe",
        checkin_code=str(uuid4()),
    )
    _db.session.add(reg)
    _db.session.commit()
    return reg


@pytest.fixture()
def unpaid_paypal_registration(app, regular_user, published_event, paid_ticket_type):
    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=paid_ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        paypal_order_id="FAKE_ORDER_123",
        payment_processor="paypal",
        checkin_code=str(uuid4()),
    )
    _db.session.add(reg)
    _db.session.commit()
    return reg


# ---------------------------------------------------------------------------
# General payment flow tests
# ---------------------------------------------------------------------------

class TestPaymentButtonVisibility:
    def test_free_ticket_shows_free_button_not_payment_buttons(
        self, client, regular_user, published_event, free_ticket_type,
        stripe_settings, paypal_settings
    ):
        """Even with both processors enabled, free-only events show Register (Free)."""
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}/register")
        assert b"Register (Free)" in resp.data
        assert b"Pay with Stripe" not in resp.data
        assert b"Pay with PayPal" not in resp.data

    def test_paid_ticket_with_stripe_only_shows_stripe_button(
        self, client, regular_user, published_event, paid_ticket_type, stripe_settings
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}/register")
        assert b"Pay with Stripe" in resp.data
        assert b"Pay with PayPal" not in resp.data
        assert b"Register" in resp.data  # pay later button

    def test_paid_ticket_with_paypal_only_shows_paypal_button(
        self, client, regular_user, published_event, paid_ticket_type, paypal_settings
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}/register")
        assert b"Pay with PayPal" in resp.data
        assert b"Pay with Stripe" not in resp.data

    def test_paid_ticket_with_both_processors_shows_both_buttons(
        self, client, regular_user, published_event, paid_ticket_type,
        stripe_settings, paypal_settings
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}/register")
        assert b"Pay with Stripe" in resp.data
        assert b"Pay with PayPal" in resp.data

    def test_free_ticket_forces_later_even_when_stripe_chosen(
        self, client, regular_user, published_event, free_ticket_type, stripe_settings
    ):
        """POST with payment_choice=stripe on a free ticket should complete without Stripe."""
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/register",
            data={"ticket_type_id": free_ticket_type.id, "payment_choice": "stripe"},
            follow_redirects=False,
        )
        # Should redirect to my_registration, not to Stripe
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert "checkout.stripe.com" not in location
        reg = Registration.query.filter_by(user_id=regular_user.id).first()
        assert reg is not None
        assert reg.stripe_session_id is None
        assert reg.payment_processor is None


# ---------------------------------------------------------------------------
# Stripe flow tests
# ---------------------------------------------------------------------------

class TestStripeRegistrationFlow:
    def test_stripe_payment_choice_creates_registration_and_redirects(
        self, client, regular_user, published_event, paid_ticket_type, stripe_settings
    ):
        _login(client, "user@example.com", "userpass123")
        mock_session = _make_stripe_session(registration_id=99)
        mock_session.id = "cs_test_new123"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_new123"

        with patch("payments.stripe") as mock_stripe:
            mock_stripe.checkout.Session.create.return_value = mock_session
            resp = client.post(
                f"/events/{published_event.slug}/register",
                data={
                    "ticket_type_id": paid_ticket_type.id,
                    "payment_choice": "stripe",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).hostname == "checkout.stripe.com"
        reg = Registration.query.filter_by(user_id=regular_user.id).first()
        assert reg is not None
        assert reg.stripe_session_id == "cs_test_new123"
        assert reg.payment_processor == "stripe"
        assert reg.payment_status == "unpaid"

    def test_stripe_api_failure_rolls_back_and_flashes_error(
        self, client, regular_user, published_event, paid_ticket_type, stripe_settings
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("payments.stripe") as mock_stripe:
            mock_stripe.checkout.Session.create.side_effect = Exception("Stripe API down")
            resp = client.post(
                f"/events/{published_event.slug}/register",
                data={
                    "ticket_type_id": paid_ticket_type.id,
                    "payment_choice": "stripe",
                },
                follow_redirects=True,
            )

        # No registration should exist after rollback
        reg = Registration.query.filter_by(user_id=regular_user.id).first()
        assert reg is None
        assert b"Could not create Stripe checkout" in resp.data


class TestStripeSuccessRoute:
    def test_marks_paid_on_valid_paid_session(
        self, client, regular_user, unpaid_stripe_registration, stripe_settings
    ):
        _login(client, "user@example.com", "userpass123")
        mock_session = _make_stripe_session(
            payment_status="paid",
            registration_id=unpaid_stripe_registration.id,
        )
        with patch("routes.account.retrieve_stripe_session", return_value=mock_session):
            resp = client.get(
                "/account/stripe/success?session_id=cs_test_fake123",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        _db.session.refresh(unpaid_stripe_registration)
        assert unpaid_stripe_registration.payment_status == "paid"
        assert unpaid_stripe_registration.payment_method == "stripe"
        assert unpaid_stripe_registration.paid_at is not None

    def test_unpaid_session_does_not_mark_paid(
        self, client, regular_user, unpaid_stripe_registration, stripe_settings
    ):
        _login(client, "user@example.com", "userpass123")
        mock_session = _make_stripe_session(
            payment_status="unpaid",
            registration_id=unpaid_stripe_registration.id,
        )
        with patch("routes.account.retrieve_stripe_session", return_value=mock_session):
            resp = client.get(
                "/account/stripe/success?session_id=cs_test_fake123",
                follow_redirects=True,
            )
        _db.session.refresh(unpaid_stripe_registration)
        assert unpaid_stripe_registration.payment_status == "unpaid"
        assert b"Payment not completed" in resp.data

    def test_idempotent_on_double_visit(
        self, client, regular_user, unpaid_stripe_registration, stripe_settings
    ):
        unpaid_stripe_registration.payment_status = "paid"
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        mock_session = _make_stripe_session(
            payment_status="paid",
            registration_id=unpaid_stripe_registration.id,
        )
        with patch("routes.account.retrieve_stripe_session", return_value=mock_session):
            resp = client.get(
                "/account/stripe/success?session_id=cs_test_fake123",
                follow_redirects=False,
            )
        # Should redirect to my_registration without error
        assert resp.status_code == 302
        assert "my-registration" in resp.headers["Location"]

    def test_wrong_user_returns_403(
        self, client, admin_user, unpaid_stripe_registration, stripe_settings
    ):
        _login(client, "admin@example.com", "adminpass123")
        mock_session = _make_stripe_session(
            payment_status="paid",
            registration_id=unpaid_stripe_registration.id,
        )
        with patch("routes.account.retrieve_stripe_session", return_value=mock_session):
            resp = client.get("/account/stripe/success?session_id=cs_test_fake123")
        assert resp.status_code == 403

    def test_invalid_session_redirects_to_dashboard(
        self, client, regular_user, stripe_settings
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("routes.account.retrieve_stripe_session", return_value=None):
            resp = client.get(
                "/account/stripe/success?session_id=bad_session",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "dashboard" in resp.headers["Location"]


class TestStripeWebhook:
    def test_valid_webhook_marks_paid(
        self, client, unpaid_stripe_registration, stripe_settings
    ):
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_status": "paid",
                    "metadata": {"registration_id": str(unpaid_stripe_registration.id)},
                }
            },
        }
        with patch("stripe.Webhook.construct_event", return_value=webhook_payload):
            resp = client.post(
                "/account/stripe/webhook",
                data=json.dumps(webhook_payload),
                content_type="application/json",
                headers={"Stripe-Signature": "fake_sig"},
            )
        assert resp.status_code == 200
        _db.session.refresh(unpaid_stripe_registration)
        assert unpaid_stripe_registration.payment_status == "paid"
        assert unpaid_stripe_registration.payment_method == "stripe"

    def test_invalid_signature_returns_400(self, client, stripe_settings):
        with patch("stripe.Webhook.construct_event", side_effect=Exception("bad sig")):
            resp = client.post(
                "/account/stripe/webhook",
                data=b"{}",
                content_type="application/json",
                headers={"Stripe-Signature": "bad"},
            )
        assert resp.status_code == 400

    def test_webhook_idempotent_when_already_paid(
        self, client, unpaid_stripe_registration, stripe_settings
    ):
        unpaid_stripe_registration.payment_status = "paid"
        _db.session.commit()
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_status": "paid",
                    "metadata": {"registration_id": str(unpaid_stripe_registration.id)},
                }
            },
        }
        with patch("stripe.Webhook.construct_event", return_value=webhook_payload):
            resp = client.post(
                "/account/stripe/webhook",
                data=json.dumps(webhook_payload),
                content_type="application/json",
                headers={"Stripe-Signature": "fake_sig"},
            )
        assert resp.status_code == 200
        # Payment status unchanged
        _db.session.refresh(unpaid_stripe_registration)
        assert unpaid_stripe_registration.payment_status == "paid"


# ---------------------------------------------------------------------------
# PayPal flow tests
# ---------------------------------------------------------------------------

class TestPaypalRegistrationFlow:
    def _mock_paypal_responses(self):
        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "fake_token"}
        token_resp.raise_for_status = MagicMock()
        order_resp = MagicMock()
        order_resp.json.return_value = {
            "id": "ORDER_NEW_456",
            "links": [
                {"rel": "self", "href": "https://api.sandbox.paypal.com/v2/checkout/orders/ORDER_NEW_456"},
                {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER_NEW_456"},
            ],
        }
        order_resp.raise_for_status = MagicMock()
        return [token_resp, order_resp]

    def test_paypal_choice_creates_registration_and_redirects(
        self, client, regular_user, published_event, paid_ticket_type, paypal_settings
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("requests.post", side_effect=self._mock_paypal_responses()):
            resp = client.post(
                f"/events/{published_event.slug}/register",
                data={
                    "ticket_type_id": paid_ticket_type.id,
                    "payment_choice": "paypal",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).hostname in (
            "www.sandbox.paypal.com", "www.paypal.com"
        )
        reg = Registration.query.filter_by(user_id=regular_user.id).first()
        assert reg is not None
        assert reg.paypal_order_id == "ORDER_NEW_456"
        assert reg.payment_processor == "paypal"
        assert reg.payment_status == "unpaid"

    def test_paypal_api_failure_rolls_back_and_flashes_error(
        self, client, regular_user, published_event, paid_ticket_type, paypal_settings
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("requests.post", side_effect=Exception("PayPal API down")):
            resp = client.post(
                f"/events/{published_event.slug}/register",
                data={
                    "ticket_type_id": paid_ticket_type.id,
                    "payment_choice": "paypal",
                },
                follow_redirects=True,
            )
        reg = Registration.query.filter_by(user_id=regular_user.id).first()
        assert reg is None
        assert b"Could not create PayPal order" in resp.data


class TestPaypalSuccessRoute:
    def test_successful_capture_marks_paid(
        self, client, regular_user, unpaid_paypal_registration, paypal_settings
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("routes.account.capture_paypal_order", return_value=True):
            resp = client.get(
                "/account/paypal/success?token=FAKE_ORDER_123",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        _db.session.refresh(unpaid_paypal_registration)
        assert unpaid_paypal_registration.payment_status == "paid"
        assert unpaid_paypal_registration.payment_method == "paypal"
        assert unpaid_paypal_registration.paid_at is not None

    def test_failed_capture_flashes_error(
        self, client, regular_user, unpaid_paypal_registration, paypal_settings
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("routes.account.capture_paypal_order", return_value=False):
            resp = client.get(
                "/account/paypal/success?token=FAKE_ORDER_123",
                follow_redirects=True,
            )
        _db.session.refresh(unpaid_paypal_registration)
        assert unpaid_paypal_registration.payment_status == "unpaid"
        assert b"Payment capture failed" in resp.data

    def test_idempotent_on_double_visit(
        self, client, regular_user, unpaid_paypal_registration, paypal_settings
    ):
        unpaid_paypal_registration.payment_status = "paid"
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.get(
            "/account/paypal/success?token=FAKE_ORDER_123",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "my-registration" in resp.headers["Location"]

    def test_wrong_user_returns_403(
        self, client, admin_user, unpaid_paypal_registration, paypal_settings
    ):
        _login(client, "admin@example.com", "adminpass123")
        with patch("routes.account.capture_paypal_order", return_value=True):
            resp = client.get("/account/paypal/success?token=FAKE_ORDER_123")
        assert resp.status_code == 403

    def test_unknown_token_redirects_to_dashboard(self, client, regular_user):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(
            "/account/paypal/success?token=UNKNOWN_TOKEN",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "dashboard" in resp.headers["Location"]


class TestPaypalWebhook:
    def test_valid_webhook_marks_paid(
        self, client, unpaid_paypal_registration, paypal_settings
    ):
        payload = json.dumps({
            "event_type": "CHECKOUT.ORDER.APPROVED",
            "resource": {"id": "FAKE_ORDER_123"},
        }).encode()
        with patch("routes.account.verify_paypal_webhook", return_value=True):
            with patch("routes.account.capture_paypal_order", return_value=True):
                resp = client.post(
                    "/account/paypal/webhook",
                    data=payload,
                    content_type="application/json",
                )
        assert resp.status_code == 200
        _db.session.refresh(unpaid_paypal_registration)
        assert unpaid_paypal_registration.payment_status == "paid"
        assert unpaid_paypal_registration.payment_method == "paypal"

    def test_invalid_signature_returns_400(self, client):
        with patch("routes.account.verify_paypal_webhook", return_value=False):
            resp = client.post(
                "/account/paypal/webhook",
                data=b"{}",
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_webhook_idempotent_when_already_paid(
        self, client, unpaid_paypal_registration, paypal_settings
    ):
        unpaid_paypal_registration.payment_status = "paid"
        _db.session.commit()
        payload = json.dumps({
            "event_type": "CHECKOUT.ORDER.APPROVED",
            "resource": {"id": "FAKE_ORDER_123"},
        }).encode()
        with patch("routes.account.verify_paypal_webhook", return_value=True):
            with patch("routes.account.capture_paypal_order", return_value=True) as mock_capture:
                resp = client.post(
                    "/account/paypal/webhook",
                    data=payload,
                    content_type="application/json",
                )
        assert resp.status_code == 200
        # capture should not have been called since already paid
        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# Admin mark-paid still works for Stripe and PayPal registrations
# ---------------------------------------------------------------------------

class TestAdminMarkPaidOnPaymentRegistrations:
    def _admin_login(self, client):
        return client.post(
            "/login",
            data={"email": "admin@example.com", "password": "adminpass123"},
            follow_redirects=False,
        )

    def test_admin_mark_paid_on_stripe_registration(
        self, client, admin_user, unpaid_stripe_registration, published_event
    ):
        self._admin_login(client)
        resp = client.post(
            f"/admin/events/{published_event.id}/registrations/{unpaid_stripe_registration.id}/mark-paid",
            data={"paid-payment_method": "cash", "paid-csrf_token": ""},
            follow_redirects=False,
        )
        _db.session.refresh(unpaid_stripe_registration)
        assert unpaid_stripe_registration.payment_status == "paid"
        assert unpaid_stripe_registration.payment_processor == "manual"

    def test_admin_mark_paid_on_paypal_registration(
        self, client, admin_user, unpaid_paypal_registration, published_event
    ):
        self._admin_login(client)
        resp = client.post(
            f"/admin/events/{published_event.id}/registrations/{unpaid_paypal_registration.id}/mark-paid",
            data={"paid-payment_method": "venmo", "paid-csrf_token": ""},
            follow_redirects=False,
        )
        _db.session.refresh(unpaid_paypal_registration)
        assert unpaid_paypal_registration.payment_status == "paid"
        assert unpaid_paypal_registration.payment_processor == "manual"
