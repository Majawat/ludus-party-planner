from flask import Blueprint, abort, redirect, render_template, flash, url_for, request
from flask_login import current_user

from forms import AdminSettingsForm
from models import SiteSettings

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

_BOOL_SETTINGS = {"registration_enabled", "show_upcoming_event_on_homepage"}


@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.url))
    if not current_user.is_admin:
        abort(403)


@admin_bp.route("/")
def dashboard():
    return render_template("admin/dashboard.html")


@admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    form = AdminSettingsForm()

    if form.validate_on_submit():
        for field in form:
            if field.name in ("submit", "csrf_token"):
                continue
            if field.name in _BOOL_SETTINGS:
                SiteSettings.set(field.name, "true" if field.data else "false")
            else:
                SiteSettings.set(field.name, field.data or "")
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    settings_dict = SiteSettings.all_as_dict()
    for field in form:
        if field.name in settings_dict:
            if field.name in _BOOL_SETTINGS:
                field.data = settings_dict[field.name] == "true"
            else:
                field.data = settings_dict[field.name]

    return render_template("admin/settings.html", form=form)
