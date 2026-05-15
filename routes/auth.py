from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import oauth
from forms import ForgotPasswordForm, LoginForm, OAuthConfirmLinkForm, RegistrationForm, ResetPasswordForm
from mailer import send_password_reset_email, send_verification_email
from models import (
    EmailVerificationToken, PasswordResetToken, SiteSettings, User,
    UserPlatformAccount, _hash_token, db, utcnow,
)

auth_bp = Blueprint("auth", __name__)

_VALID_PROVIDERS = {"discord", "google"}

_PROVIDER_CONFIG = {
    "discord": {
        "client_kwargs": {"scope": "identify email"},
        "authorize_url": "https://discord.com/api/oauth2/authorize",
        "access_token_url": "https://discord.com/api/oauth2/token",
        "api_base_url": "https://discord.com/api/",
    },
    "google": {
        "client_kwargs": {"scope": "openid email profile"},
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
    },
}


def get_oauth_client(provider):
    settings = SiteSettings.all_as_dict()
    client_id = settings.get(f"{provider}_oauth_client_id", "")
    client_secret = settings.get(f"{provider}_oauth_client_secret", "")
    if not client_id or not client_secret:
        return None
    config = dict(_PROVIDER_CONFIG[provider])
    return oauth.register(
        name=provider,
        client_id=client_id,
        client_secret=client_secret,
        overwrite=True,
        **config,
    )


def _get_configured_providers():
    settings = SiteSettings.all_as_dict()
    providers = []
    if settings.get("discord_oauth_client_id") and settings.get("discord_oauth_client_secret"):
        providers.append("discord")
    if settings.get("google_oauth_client_id") and settings.get("google_oauth_client_secret"):
        providers.append("google")
    return providers


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
    oauth_providers = _get_configured_providers()
    return render_template("auth/register.html", form=form, oauth_providers=oauth_providers)


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
    oauth_providers = _get_configured_providers()
    return render_template("auth/login.html", form=form, oauth_providers=oauth_providers)


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


# ---------------------------------------------------------------------------
# OAuth routes
# ---------------------------------------------------------------------------

@auth_bp.route("/auth/<provider>/login")
def oauth_login(provider):
    if provider not in _VALID_PROVIDERS:
        from flask import abort
        abort(404)
    client = get_oauth_client(provider)
    if client is None:
        from flask import abort
        abort(404)
    if current_user.is_authenticated:
        session["oauth_connecting"] = True
    callback_url = url_for("auth.oauth_callback", provider=provider, _external=True)
    return client.authorize_redirect(callback_url)


@auth_bp.route("/auth/<provider>/callback")
def oauth_callback(provider):
    from flask import abort
    if provider not in _VALID_PROVIDERS:
        abort(404)
    client = get_oauth_client(provider)
    if client is None:
        abort(404)

    token = client.authorize_access_token()

    if provider == "discord":
        resp = client.get("users/@me", token=token)
        profile = resp.json()
        provider_user_id = str(profile["id"])
        username = profile.get("global_name") or profile.get("username") or "Unknown"
        email = profile.get("email")
    else:  # google
        user_info = token.get("userinfo") or {}
        provider_user_id = str(user_info.get("sub", ""))
        username = user_info.get("name") or user_info.get("email") or "Unknown"
        email = user_info.get("email")

    connecting = session.pop("oauth_connecting", False)

    if connecting and current_user.is_authenticated:
        # Account linking from profile page
        existing = UserPlatformAccount.query.filter_by(
            platform=provider, platform_user_id=provider_user_id
        ).first()
        if existing:
            if existing.user_id == current_user.id:
                flash(f"This {provider.capitalize()} account is already linked to your account.", "info")
            else:
                flash(f"This {provider.capitalize()} account is already linked to a different Ludus account.", "error")
            return redirect(url_for("account.profile"))
        acct = UserPlatformAccount(
            user_id=current_user.id,
            platform=provider,
            username=username,
            platform_user_id=provider_user_id,
        )
        db.session.add(acct)
        db.session.commit()
        flash(f"{provider.capitalize()} account linked successfully.", "success")
        return redirect(url_for("account.profile"))

    # 1. Find existing platform account → log in
    platform_acct = UserPlatformAccount.query.filter_by(
        platform=provider, platform_user_id=provider_user_id
    ).first()
    if platform_acct:
        login_user(platform_acct.user)
        return redirect(url_for("account.dashboard"))

    # 2. Email matches existing user → ask to confirm link
    if email:
        existing_user = User.query.filter_by(email=email.lower()).first()
        if existing_user:
            session["oauth_pending_link"] = {
                "provider": provider,
                "provider_user_id": provider_user_id,
                "username": username,
                "email": email.lower(),
            }
            return render_template(
                "auth/oauth_confirm_link.html",
                provider=provider,
                email=email,
                form=OAuthConfirmLinkForm(),
            )

    # 3. Create new user
    if not email:
        flash(
            f"Could not retrieve your email from {provider.capitalize()}. "
            "Please verify your email with the provider and try again.",
            "error",
        )
        return redirect(url_for("auth.login"))

    new_user = User(
        name=username,
        email=email.lower(),
        email_verified_at=utcnow(),
    )
    db.session.add(new_user)
    db.session.flush()
    acct = UserPlatformAccount(
        user_id=new_user.id,
        platform=provider,
        username=username,
        platform_user_id=provider_user_id,
    )
    db.session.add(acct)
    db.session.commit()
    login_user(new_user)
    flash("Welcome! You can add a password in your profile settings.", "success")
    return redirect(url_for("account.dashboard"))


@auth_bp.route("/auth/<provider>/confirm-link", methods=["POST"])
def oauth_confirm_link(provider):
    from flask import abort
    if provider not in _VALID_PROVIDERS:
        abort(404)

    form = OAuthConfirmLinkForm()
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url_for("auth.login"))

    pending = session.pop("oauth_pending_link", None)
    if pending is None or pending.get("provider") != provider:
        flash("Session expired. Please try logging in again.", "error")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=pending["email"]).first()
    if user is None:
        flash("Account not found.", "error")
        return redirect(url_for("auth.login"))

    existing = UserPlatformAccount.query.filter_by(
        platform=pending["provider"], platform_user_id=pending["provider_user_id"]
    ).first()
    if existing:
        flash(f"This {provider.capitalize()} account is already linked to another account.", "error")
        return redirect(url_for("auth.login"))

    acct = UserPlatformAccount(
        user_id=user.id,
        platform=pending["provider"],
        username=pending["username"],
        platform_user_id=pending["provider_user_id"],
    )
    db.session.add(acct)
    db.session.commit()
    login_user(user)
    flash(f"{provider.capitalize()} account linked to your existing account.", "success")
    return redirect(url_for("account.dashboard"))
