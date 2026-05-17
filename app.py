import os
import click
from flask import Flask, jsonify, render_template
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from dotenv import load_dotenv

from extensions import csrf, oauth
from models import db, User, SiteSettings, Event, TicketType, get_allowed_themes

migrate = Migrate()
login_manager = LoginManager()
mail = Mail()


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config is None:
        load_dotenv()

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///data/ludus.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "localhost")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT") or 587)
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
    app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")

    if test_config:
        app.config.update(test_config)

    # Flask-SQLAlchemy 3.x resolves relative SQLite paths to the instance folder.
    # Convert relative paths to absolute relative to app.root_path instead, so the
    # database stays at <project>/data/ludus.db rather than <project>/instance/data/ludus.db.
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////") and ":memory:" not in db_url:
        db_path = os.path.join(app.root_path, db_url.removeprefix("sqlite:///"))
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    oauth.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from routes import register_blueprints
    register_blueprints(app)

    @app.context_processor
    def inject_site_settings():
        try:
            theme = SiteSettings.get("ui_theme", "dark")
            site_name = SiteSettings.get("site_name", "Ludus Party Planner")
            site_tagline = SiteSettings.get("site_tagline", "Board Games & LAN Parties")
            # Use `or` so an empty stored string falls back to the safe default,
            # not just a missing key (SiteSettings.get default only fires on None).
            default_dark_theme = SiteSettings.get("default_dark_theme") or "dark"
            default_light_theme = SiteSettings.get("default_light_theme") or "light"
            allowed_themes = get_allowed_themes()
        except Exception as e:
            app.logger.warning(f"inject_site_settings failed: {e}")
            theme = "dark"
            site_name = "Ludus Party Planner"
            site_tagline = "Board Games & LAN Parties"
            default_dark_theme = "dark"
            default_light_theme = "light"
            allowed_themes = []
        return {
            "ui_theme": theme,
            "site_name": site_name,
            "site_tagline": site_tagline,
            "default_dark_theme": default_dark_theme,
            "default_light_theme": default_light_theme,
            "allowed_themes": allowed_themes,
        }

    @app.before_request
    def check_setup():
        from flask import request as req, redirect, url_for
        # Skip setup routes, static files, and health check
        if (
            req.path.startswith("/setup")
            or req.path.startswith("/static")
            or req.path == "/ping"
        ):
            return None
        try:
            admin_exists = User.query.filter_by(is_admin=True).first() is not None
            setup_complete = SiteSettings.get("setup_complete", "false") == "true"
            if not admin_exists or not setup_complete:
                return redirect(url_for("setup.step1"))
        except Exception as e:
            app.logger.warning(f"check_setup before_request failed: {e}")

    @app.route("/ping")
    def ping():
        return jsonify({"status": "ok"})

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    _SETTING_DEFAULTS = {
        "site_name": "Ludus Party Planner",
        "site_tagline": "Board Games & LAN Parties",
        "contact_email": "",
        "logo_url": "",
        "favicon_url": "",
        "discord_url": "",
        "twitch_url": "",
        "youtube_url": "",
        "instagram_url": "",
        "facebook_url": "",
        "terms_of_service": "",
        "privacy_policy": "",
        "registration_enabled": "true",
        "show_upcoming_event_on_homepage": "true",
        "venmo_handle": "",
        "ui_theme": "dark",
        "default_dark_theme": "dark",
        "default_light_theme": "light",
        "allowed_themes": "",
        "discord_oauth_client_id": "",
        "discord_oauth_client_secret": "",
        "google_oauth_client_id": "",
        "google_oauth_client_secret": "",
        "steam_enabled": "false",
        "steam_api_key": "",
        "stripe_enabled": "false",
        "stripe_publishable_key": "",
        "stripe_secret_key": "",
        "stripe_webhook_secret": "",
        "paypal_enabled": "false",
        "paypal_client_id": "",
        "paypal_client_secret": "",
        "paypal_mode": "sandbox",
        "paypal_webhook_id": "",
        "challonge_api_key": "",
        "challonge_username": "",
        "itad_api_key": "",
        "passkeys_enabled": "false",
        "webauthn_rp_id": "",
        "webauthn_origin": "",
    }

    @app.cli.command("seed-settings")
    def seed_settings():
        """Seed site_settings with default values (idempotent)."""
        count = 0
        for key, value in _SETTING_DEFAULTS.items():
            if db.session.get(SiteSettings, key) is None:
                db.session.add(SiteSettings(key=key, value=value))
                count += 1
        db.session.commit()
        click.echo(f"Seeded {count} setting(s). Existing values not changed.")

    @app.cli.command("create-admin")
    @click.argument("email")
    def create_admin(email):
        """Promote a user to admin by email address."""
        user = User.query.filter_by(email=email).first()
        if not user:
            click.echo(f"No user found with email: {email}")
            return
        user.is_admin = True
        db.session.commit()
        click.echo(f"'{user.name}' ({email}) is now an admin.")

    @app.cli.command("seed-setup")
    def seed_setup():
        """Reset setup_complete to false (for dev/testing to re-run the wizard)."""
        SiteSettings.set("setup_complete", "false")
        click.echo("setup_complete reset to false. Visit /setup to run the wizard again.")

    @app.cli.command("seed-event")
    def seed_event():
        """Seed one published test event (idempotent)."""
        from datetime import datetime
        slug = "lan-party-2026"
        if db.session.execute(db.select(Event).filter_by(slug=slug)).scalar_one_or_none():
            click.echo("Test event already exists. Skipping.")
            return
        event = Event(
            name="LAN Party 2026",
            slug=slug,
            type="lan",
            status="published",
            short_description="Our annual LAN party returns! Three days of gaming, friends, and fun.",
            description=(
                "<p>Join us for the annual Ludus LAN Party! Bring your rig or borrow one of ours.</p>"
                "<p><strong>What to bring:</strong> Your PC, monitor, peripherals, and snacks to share.</p>"
                "<p>Doors open Friday evening. Full schedule posted closer to the date.</p>"
            ),
            start_datetime=datetime(2026, 8, 7, 18, 0, 0),
            end_datetime=datetime(2026, 8, 9, 18, 0, 0),
            location="Community Center, 123 Main St, Springfield",
            seating_enabled=True,
            registration_open=True,
        )
        db.session.add(event)
        db.session.commit()
        click.echo(f"Seeded event: '{event.name}' (slug: {event.slug})")

    return app
