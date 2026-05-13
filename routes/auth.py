from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from forms import ForgotPasswordForm, LoginForm, RegistrationForm, ResetPasswordForm
from mailer import send_password_reset_email, send_verification_email
from models import EmailVerificationToken, PasswordResetToken, User, _hash_token, db, utcnow

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("account.dashboard"))
    form = RegistrationForm()
    if form.validate_on_submit():
        if form.website.data:
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("auth.login"))
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("An account with that email already exists.", "error")
            return redirect(url_for("auth.register"))
        user = User(
            name=form.name.data,
            email=form.email.data.lower(),
            newsletter_opt_in=form.newsletter_opt_in.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        raw_token = EmailVerificationToken.create_for_user(user)
        db.session.commit()
        send_verification_email(user, raw_token)
        flash("Account created! Check your email to verify your address.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("account.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get("next")
            if next_page and next_page.startswith("/"):
                return redirect(next_page)
            return redirect(url_for("account.dashboard"))
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.index"))


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    token_hash = _hash_token(token)
    record = EmailVerificationToken.query.filter_by(token_hash=token_hash).first()
    if not record or record.expires_at < utcnow():
        flash("This verification link is invalid or has expired.", "error")
        return redirect(url_for("public.index"))
    user = record.user
    user.email_verified_at = utcnow()
    db.session.delete(record)
    db.session.commit()
    flash("Email verified! You can now register for events.", "success")
    if current_user.is_authenticated:
        return redirect(url_for("account.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/resend-verification", methods=["POST"])
@login_required
def resend_verification():
    if current_user.is_verified:
        return redirect(url_for("account.dashboard"))
    EmailVerificationToken.query.filter_by(user_id=current_user.id).delete()
    raw_token = EmailVerificationToken.create_for_user(current_user)
    db.session.commit()
    send_verification_email(current_user, raw_token)
    flash("Verification email resent.", "success")
    return redirect(url_for("account.dashboard"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            raw_token = PasswordResetToken.create_for_user(user)
            db.session.commit()
            send_password_reset_email(user, raw_token)
        flash("If that email is registered, you'll receive a reset link shortly.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    token_hash = _hash_token(token)
    record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
    if not record or not record.is_valid:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        record.user.set_password(form.password.data)
        record.used_at = utcnow()
        db.session.commit()
        flash("Password updated. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form, token=token)
