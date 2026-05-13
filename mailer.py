from flask import url_for
from flask_mail import Message


def send_verification_email(user, raw_token):
    from app import mail
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


def send_registration_confirmation_email(registration):
    from app import mail
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
