from flask import Blueprint, render_template
from flask_login import login_required

account_bp = Blueprint("account", __name__)


@account_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("account/dashboard.html")


@account_bp.route("/account")
@login_required
def profile():
    return render_template("account/profile.html")
