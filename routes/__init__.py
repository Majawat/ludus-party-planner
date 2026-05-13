from routes.public import public_bp
from routes.auth import auth_bp
from routes.account import account_bp
from routes.admin import admin_bp


def register_blueprints(app):
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(admin_bp)
