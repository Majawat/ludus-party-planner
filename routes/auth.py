import requests
from openid.consumer.consumer import Consumer, SUCCESS
from openid.store.memstore import MemoryStore
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import csrf, oauth
from webauthn import (
    generate_registration_options,
    generate_authentication_options,
    verify_registration_response,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
)
from forms import (
    ForgotPasswordForm, LoginForm, OAuthConfirmLinkForm, RegistrationForm,
    ResetPasswordForm, SteamCompleteRegistrationForm,
)
from mailer import send_password_reset_email, send_verification_email
from models import (
    EmailVerificationToken, PasswordResetToken, SiteSettings, User,
    UserPlatformAccount, WebAuthnCredential, _hash_token, db, utcnow,
)

auth_bp = Blueprint("auth", __name__)

_VALID_PROVIDERS = {"discord", "google"}
_openid_store = MemoryStore()
STEAM_OPENID_URL = "https://steamcommunity.com/openid"


def _get_rp_id():
    configured = SiteSettings.get("webauthn_rp_id", "").strip()
    if configured:
        return configured
    return request.host.split(":")[0]


def _get_origin():
    configured = SiteSettings.get("webauthn_origin", "").strip()
    if configured:
        return configured.rstrip("/")
    return request.host_url.rstrip("/")

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
    steam_enabled = SiteSettings.get("steam_enabled") == "true"
    return render_template("auth/register.html", form=form, oauth_providers=oauth_providers, steam_enabled=steam_enabled)


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
            if next_page:
                next_page = next_page.replace("\\", "")
                parsed = urlparse(next_page)
                if not parsed.netloc and not parsed.scheme:
                    return redirect(next_page)
            return redirect(url_for("account.dashboard"))
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))
    oauth_providers = _get_configured_providers()
    steam_enabled = SiteSettings.get("steam_enabled") == "true"
    passkeys_enabled = SiteSettings.get("passkeys_enabled") == "true"
    return render_template("auth/login.html", form=form, oauth_providers=oauth_providers,
                           steam_enabled=steam_enabled, passkeys_enabled=passkeys_enabled)


@auth_bp.route("/logout", methods=["POST"])
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
        abort(404)
    client = get_oauth_client(provider)
    if client is None:
        abort(404)
    if current_user.is_authenticated:
        session["oauth_connecting"] = True
    callback_url = url_for("auth.oauth_callback", provider=provider, _external=True)
    return client.authorize_redirect(callback_url)


@auth_bp.route("/auth/<provider>/callback")
def oauth_callback(provider):
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


# ---------------------------------------------------------------------------
# Steam OpenID routes
# ---------------------------------------------------------------------------

def _fetch_steam_persona(steam64_id):
    api_key = SiteSettings.get("steam_api_key", "")
    if not api_key:
        return "Steam User"
    try:
        r = requests.get(
            "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
            params={"key": api_key, "steamids": steam64_id},
            timeout=3,
        )
        return r.json()["response"]["players"][0]["personaname"]
    except Exception:
        return "Steam User"


@auth_bp.route("/auth/steam/login")
def steam_login():
    if SiteSettings.get("steam_enabled") != "true":
        abort(404)
    if current_user.is_authenticated:
        session["steam_connecting"] = True
    consumer = Consumer(session, _openid_store)
    try:
        auth_request = consumer.begin(STEAM_OPENID_URL)
    except Exception:
        flash("Could not connect to Steam. Please try again.", "error")
        return redirect(url_for("auth.login"))
    callback_url = url_for("auth.steam_callback", _external=True)
    realm = request.host_url.rstrip("/")
    return redirect(auth_request.redirectURL(realm, callback_url))


@auth_bp.route("/auth/steam/callback")
def steam_callback():
    if SiteSettings.get("steam_enabled") != "true":
        abort(404)
    consumer = Consumer(session, _openid_store)
    response = consumer.complete(request.args.to_dict(), request.url)
    if response.status != SUCCESS:
        flash("Steam login failed or was cancelled.", "error")
        return redirect(url_for("auth.login"))

    steam64_id = response.identity_url.split("/")[-1]
    persona_name = _fetch_steam_persona(steam64_id)
    connecting = session.pop("steam_connecting", False)

    if connecting and current_user.is_authenticated:
        existing = UserPlatformAccount.query.filter_by(
            platform="steam", platform_user_id=steam64_id
        ).first()
        if existing:
            if existing.user_id == current_user.id:
                flash("This Steam account is already linked to your account.", "info")
            else:
                flash("This Steam account is already linked to a different Ludus account.", "error")
            return redirect(url_for("account.profile"))
        db.session.add(UserPlatformAccount(
            user_id=current_user.id,
            platform="steam",
            username=persona_name,
            platform_user_id=steam64_id,
        ))
        db.session.commit()
        flash("Steam account linked successfully.", "success")
        return redirect(url_for("account.profile"))

    platform_acct = UserPlatformAccount.query.filter_by(
        platform="steam", platform_user_id=steam64_id
    ).first()
    if platform_acct:
        login_user(platform_acct.user)
        return redirect(url_for("account.dashboard"))

    session["steam_pending"] = {"steam64_id": steam64_id, "persona_name": persona_name}
    return redirect(url_for("auth.steam_complete_registration"))


@auth_bp.route("/auth/steam/complete-registration", methods=["GET", "POST"])
def steam_complete_registration():
    if SiteSettings.get("steam_enabled") != "true":
        abort(404)
    pending = session.get("steam_pending")
    if not pending or not pending.get("steam64_id"):
        return redirect(url_for("auth.login"))

    form = SteamCompleteRegistrationForm()
    if request.method == "GET":
        form.name.data = pending.get("persona_name", "")

    if form.validate_on_submit():
        email = form.email.data.lower()
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("auth/steam_complete_registration.html", form=form)
        new_user = User(name=form.name.data, email=email, email_verified_at=utcnow())
        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.flush()
        db.session.add(UserPlatformAccount(
            user_id=new_user.id,
            platform="steam",
            username=pending.get("persona_name", "Steam User"),
            platform_user_id=pending["steam64_id"],
        ))
        db.session.commit()
        session.pop("steam_pending", None)
        login_user(new_user)
        flash("Account created! You can now register for events.", "success")
        return redirect(url_for("account.dashboard"))

    return render_template("auth/steam_complete_registration.html", form=form)


# ---------------------------------------------------------------------------
# WebAuthn / Passkeys routes
# ---------------------------------------------------------------------------

@auth_bp.route("/auth/passkey/register/begin")
@csrf.exempt
@login_required
def passkey_register_begin():
    if SiteSettings.get("passkeys_enabled") != "true":
        abort(404)
    options = generate_registration_options(
        rp_id=_get_rp_id(),
        rp_name=SiteSettings.get("site_name", "Ludus Party Planner"),
        user_id=str(current_user.id).encode(),
        user_name=current_user.email,
        user_display_name=current_user.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            {"id": base64url_to_bytes(c.credential_id), "type": "public-key"}
            for c in current_user.passkey_credentials
        ],
    )
    session["webauthn_register_challenge"] = options.challenge.hex()
    return options_to_json(options), 200, {"Content-Type": "application/json"}


@auth_bp.route("/auth/passkey/register/complete", methods=["POST"])
@csrf.exempt
@login_required
def passkey_register_complete():
    if SiteSettings.get("passkeys_enabled") != "true":
        abort(404)
    challenge_hex = session.pop("webauthn_register_challenge", None)
    if not challenge_hex:
        return {"error": "No challenge"}, 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {"error": "Invalid JSON"}, 400
    try:
        verification = verify_registration_response(
            credential=body,
            expected_challenge=bytes.fromhex(challenge_hex),
            expected_rp_id=_get_rp_id(),
            expected_origin=_get_origin(),
            require_user_verification=False,
        )
    except Exception as e:
        current_app.logger.warning(f"Passkey registration failed: {e}")
        return {"error": "Verification failed"}, 400
    device_name = (body.get("device_name", "") or "").strip()[:64] or None
    cred = WebAuthnCredential(
        user_id=current_user.id,
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=bytes_to_base64url(verification.credential_public_key),
        sign_count=verification.sign_count,
        device_name=device_name,
        aaguid=str(verification.aaguid) if verification.aaguid else None,
    )
    db.session.add(cred)
    db.session.commit()
    return {"ok": True}


@auth_bp.route("/auth/passkey/login/begin")
@csrf.exempt
def passkey_login_begin():
    if SiteSettings.get("passkeys_enabled") != "true":
        abort(404)
    options = generate_authentication_options(
        rp_id=_get_rp_id(),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    session["webauthn_auth_challenge"] = options.challenge.hex()
    return options_to_json(options), 200, {"Content-Type": "application/json"}


@auth_bp.route("/auth/passkey/login/complete", methods=["POST"])
@csrf.exempt
def passkey_login_complete():
    if SiteSettings.get("passkeys_enabled") != "true":
        abort(404)
    challenge_hex = session.pop("webauthn_auth_challenge", None)
    if not challenge_hex:
        return {"error": "No challenge"}, 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {"error": "Invalid JSON"}, 400
    raw_id = body.get("rawId") or body.get("id")
    cred = WebAuthnCredential.query.filter_by(credential_id=raw_id).first()
    if not cred:
        return {"error": "Credential not found"}, 400
    try:
        verification = verify_authentication_response(
            credential=body,
            expected_challenge=bytes.fromhex(challenge_hex),
            expected_rp_id=_get_rp_id(),
            expected_origin=_get_origin(),
            credential_public_key=base64url_to_bytes(cred.public_key),
            credential_current_sign_count=cred.sign_count,
            require_user_verification=False,
        )
    except Exception as e:
        current_app.logger.warning(f"Passkey auth failed: {e}")
        return {"error": "Verification failed"}, 400
    cred.sign_count = verification.new_sign_count
    cred.last_used_at = utcnow()
    db.session.commit()
    if getattr(cred.user, "totp_secret", None):
        session["pending_2fa_user_id"] = cred.user.id
        return {"ok": True, "redirect": url_for("auth.verify_2fa")}
    login_user(cred.user)
    return {"ok": True, "redirect": url_for("account.dashboard")}


@auth_bp.route("/auth/passkey/remove/<int:cred_id>", methods=["POST"])
@login_required
def passkey_remove(cred_id):
    if SiteSettings.get("passkeys_enabled") != "true":
        abort(404)
    cred = db.session.get(WebAuthnCredential, cred_id)
    if cred is None or cred.user_id != current_user.id:
        abort(403)
    cred_count = WebAuthnCredential.query.filter_by(user_id=current_user.id).count()
    if cred_count <= 1 and not current_user.has_password:
        flash("You must set a password before removing your last passkey.", "error")
        return redirect(url_for("account.profile"))
    db.session.delete(cred)
    db.session.commit()
    flash("Passkey removed.", "success")
    return redirect(url_for("account.profile"))
