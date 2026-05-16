import json

import stripe
import requests as http

from models import SiteSettings


# ── Stripe ───────────────────────────────────────────────────────────────────

def create_stripe_session(registration, event, ticket_type, success_url, cancel_url, customer_email=None):
    """Return (session_id, checkout_url) or raise on API error."""
    stripe.api_key = SiteSettings.get("stripe_secret_key", "")
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"{event.name} — {ticket_type.name}"},
                "unit_amount": int(ticket_type.price * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        metadata={"registration_id": str(registration.id)},
        success_url=success_url,
        cancel_url=cancel_url,
        **({"customer_email": customer_email} if customer_email else {}),
    )
    return session.id, session.url


def retrieve_stripe_session(session_id):
    """Return the Stripe Session object, or None on any error."""
    try:
        stripe.api_key = SiteSettings.get("stripe_secret_key", "")
        return stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return None


# ── PayPal internals ──────────────────────────────────────────────────────────

def _get_paypal_base_url():
    """Return the PayPal REST API base URL."""
    if SiteSettings.get("paypal_mode", "sandbox") == "live":
        return "https://api-m.paypal.com"
    return "https://api-m.sandbox.paypal.com"


def _get_paypal_checkout_base_url():
    """Return the user-facing PayPal checkout URL base."""
    if SiteSettings.get("paypal_mode", "sandbox") == "live":
        return "https://www.paypal.com"
    return "https://www.sandbox.paypal.com"


def _get_paypal_access_token():
    """Return (access_token, base_url) or raise on error."""
    base_url = _get_paypal_base_url()
    resp = http.post(
        f"{base_url}/v1/oauth2/token",
        auth=(
            SiteSettings.get("paypal_client_id", ""),
            SiteSettings.get("paypal_client_secret", ""),
        ),
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"], base_url


# ── PayPal public API ─────────────────────────────────────────────────────────

def create_paypal_order(registration, event, ticket_type, return_url, cancel_url):
    """Return (order_id, approve_url) or raise on API error."""
    token, base_url = _get_paypal_access_token()
    resp = http.post(
        f"{base_url}/v2/checkout/orders",
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": "USD",
                    "value": f"{ticket_type.price:.2f}",
                },
                "description": f"{event.name} — {ticket_type.name}",
                "custom_id": str(registration.id),
            }],
            "application_context": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "brand_name": SiteSettings.get("site_name", "Ludus Party Planner"),
                "user_action": "PAY_NOW",
            },
        },
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    approve_url = next(link["href"] for link in data["links"] if link["rel"] == "approve")
    return data["id"], approve_url


def capture_paypal_order(order_id):
    """Return True if the order captured successfully, False on any error."""
    try:
        token, base_url = _get_paypal_access_token()
        resp = http.post(
            f"{base_url}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("status") == "COMPLETED"
    except Exception:
        return False


def verify_paypal_webhook(headers, raw_body):
    """Return True if PayPal confirms the webhook signature is valid."""
    try:
        token, base_url = _get_paypal_access_token()
        resp = http.post(
            f"{base_url}/v1/notifications/verify-webhook-signature",
            json={
                "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
                "cert_url": headers.get("PAYPAL-CERT-URL"),
                "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
                "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
                "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
                "webhook_id": SiteSettings.get("paypal_webhook_id", ""),
                "webhook_event": json.loads(raw_body),
            },
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10,
        )
        return resp.json().get("verification_status") == "SUCCESS"
    except Exception:
        return False
