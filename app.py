import os
import click
from flask import Flask, jsonify, render_template
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

from models import db, User, SiteSettings

migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()


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
        except Exception:
            theme = "dark"
            site_name = "Ludus Party Planner"
            site_tagline = "Board Games & LAN Parties"
        return {"ui_theme": theme, "site_name": site_name, "site_tagline": site_tagline}

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

    return app
