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
