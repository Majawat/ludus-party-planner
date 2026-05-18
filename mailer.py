import html as _html_mod
import re
from html.parser import HTMLParser

from flask import current_app, url_for
from flask_mail import Message


def _apply_mail_settings():
    """Read mail config from site_settings and update app.config.
    Called before every send so config is always current."""
    from models import SiteSettings
    try:
        port_str = SiteSettings.get("mail_port", "587") or "587"
        port = int(port_str) if port_str.isdigit() else 587
        username = SiteSettings.get("mail_username", "") or None
        password = SiteSettings.get("mail_password", "") or None
        sender = SiteSettings.get("mail_default_sender", "")
        current_app.config.update({
            "MAIL_SERVER": SiteSettings.get("mail_server", ""),
            "MAIL_PORT": port,
            "MAIL_USE_TLS": SiteSettings.get("mail_use_tls", "true") == "true",
            "MAIL_USERNAME": username,
            "MAIL_PASSWORD": password,
            "MAIL_DEFAULT_SENDER": sender,
            "MAIL_SUPPRESS_SEND": not bool(
                SiteSettings.get("mail_server", "").strip()),
        })
    except Exception as e:
        current_app.logger.warning(f"_apply_mail_settings failed: {e}")


class _StripTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []

    def handle_data(self, data):
        self._chunks.append(data)


def _html_to_plain(html_str: str) -> str:
    parser = _StripTags()
    parser.feed(html_str)
    text = " ".join(parser._chunks)
    text = _html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def send_verification_email(user, raw_token):
    from app import mail
    _apply_mail_settings()
    verify_url = url_for("auth.verify_email", token=raw_token, _external=True)
    msg = Message(
        subject="Verify your Ludus Party Planner account",
        recipients=[user.email],
        body=(
            f"Hi {user.name},\n\n"
            f"Verify your email address:\n{verify_url}\n\n"
            "This link expires in 48 hours."
        ),
        html=(
            f"<p>Hi {user.name},</p>"
            f"<p><a href='{verify_url}'>Verify your email address</a></p>"
            "<p>This link expires in 48 hours.</p>"
        ),
    )
    mail.send(msg)


def send_password_reset_email(user, raw_token):
    from app import mail
    _apply_mail_settings()
    reset_url = url_for("auth.reset_password", token=raw_token, _external=True)
    msg = Message(
        subject="Reset your Ludus Party Planner password",
        recipients=[user.email],
        body=(
            f"Hi {user.name},\n\n"
            f"Reset your password:\n{reset_url}\n\n"
            "This link expires in 1 hour. If you didn't request this, ignore this email."
        ),
        html=(
            f"<p>Hi {user.name},</p>"
            f"<p><a href='{reset_url}'>Reset your password</a></p>"
            "<p>This link expires in 1 hour. If you didn't request this, ignore this email.</p>"
        ),
    )
    mail.send(msg)


def send_registration_pending_payment_email(registration):
    """Sent when a user starts a Stripe or PayPal checkout — payment not yet complete."""
    from app import mail
    _apply_mail_settings()
    my_reg_url = url_for(
        "account.my_registration",
        slug=registration.event.slug,
        _external=True,
    )
    event = registration.event
    ticket = registration.ticket_type
    msg = Message(
        subject=f"Complete your payment: {event.name}",
        recipients=[registration.user.email],
        body=(
            f"Hi {registration.user.name},\n\n"
            f"Your spot at {event.name} is reserved but payment is not yet complete.\n\n"
            f"Ticket: {ticket.name} (${ticket.price:.2f})\n"
            f"Date: {event.start_datetime.strftime('%B %-d, %Y')}\n"
            f"Location: {event.location}\n\n"
            f"Complete your payment here:\n{my_reg_url}\n\n"
            "If you did not register, please ignore this email."
        ),
        html=(
            f"<p>Hi {registration.user.name},</p>"
            f"<p>Your spot at <strong>{event.name}</strong> is reserved but payment is not yet complete.</p>"
            f"<ul>"
            f"<li><strong>Ticket:</strong> {ticket.name} (${ticket.price:.2f})</li>"
            f"<li><strong>Date:</strong> {event.start_datetime.strftime('%B %-d, %Y')}</li>"
            f"<li><strong>Location:</strong> {event.location}</li>"
            f"</ul>"
            f"<p><a href='{my_reg_url}'>Complete your payment</a></p>"
            "<p>If you did not register, please ignore this email.</p>"
        ),
    )
    mail.send(msg)


def send_mass_email(recipients, subject, html_body):
    from app import mail
    _apply_mail_settings()
    success_count = 0
    failed = []
    plain_body = _html_to_plain(html_body)
    for user in recipients:
        msg = Message(subject=subject, recipients=[user.email])
        msg.html = html_body
        msg.body = plain_body
        try:
            mail.send(msg)
            success_count += 1
        except Exception as e:
            current_app.logger.warning("mailer: failed to send to %s: %s", user.email, e)
            failed.append(user.email)
    return success_count, failed


def send_registration_confirmation_email(registration):
    from app import mail
    _apply_mail_settings()
    my_reg_url = url_for(
        "account.my_registration",
        slug=registration.event.slug,
        _external=True,
    )
    event = registration.event
    ticket = registration.ticket_type
    price_str = "Free" if ticket.price == 0 else f"${ticket.price:.2f}"
    msg = Message(
        subject=f"Registration confirmed: {event.name}",
        recipients=[registration.user.email],
        body=(
            f"Hi {registration.user.name},\n\n"
            f"You're registered for {event.name}!\n\n"
            f"Ticket: {ticket.name} ({price_str})\n"
            f"Date: {event.start_datetime.strftime('%B %-d, %Y')}\n"
            f"Location: {event.location}\n\n"
            f"View your registration:\n{my_reg_url}\n\n"
            "See you there!"
        ),
        html=(
            f"<p>Hi {registration.user.name},</p>"
            f"<p>You're registered for <strong>{event.name}</strong>!</p>"
            f"<ul>"
            f"<li><strong>Ticket:</strong> {ticket.name} ({price_str})</li>"
            f"<li><strong>Date:</strong> {event.start_datetime.strftime('%B %-d, %Y')}</li>"
            f"<li><strong>Location:</strong> {event.location}</li>"
            f"</ul>"
            f"<p><a href='{my_reg_url}'>View your registration</a></p>"
            "<p>See you there!</p>"
        ),
    )
    mail.send(msg)
