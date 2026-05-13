from flask import Blueprint, render_template

account_bp = Blueprint("account", __name__)


@account_bp.route("/dashboard")
def dashboard():
    return render_template("account/dashboard.html")


@account_bp.route("/account")
def profile():
    return render_template("account/profile.html")
