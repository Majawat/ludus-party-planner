import os
import click
from flask import Flask, jsonify, render_template
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

from models import db

load_dotenv()

migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__)

    # --- Config ---
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///data/ludus.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "localhost")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
    app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")

    if test_config:
        app.config.update(test_config)

    # Ensure the data directory exists for SQLite
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_url.startswith("sqlite:///") and ":memory:" not in db_url:
        db_path = db_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.join(app.root_path, db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # --- Extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # Placeholder user_loader — replaced in Phase 1 when the User model exists.
    @login_manager.user_loader
    def load_user(user_id):
        return None

    # --- Blueprints ---
    from routes import register_blueprints
    register_blueprints(app)

    # --- Health check ---
    @app.route("/ping")
    def ping():
        return jsonify({"status": "ok"})

    # --- Error handlers ---
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    # --- CLI commands ---
    @app.cli.command("seed-settings")
    def seed_settings():
        """Seed site_settings with default values (idempotent)."""
        click.echo("seed-settings: will be implemented in Phase 2.")

    @app.cli.command("create-admin")
    @click.argument("email")
    def create_admin(email):
        """Promote a user to admin by email address."""
        click.echo(f"create-admin: will be implemented in Phase 2. (email={email})")

    return app
