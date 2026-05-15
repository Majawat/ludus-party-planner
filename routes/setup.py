from flask import Blueprint, flash, redirect, render_template, url_for

from forms import SetupAdminForm, SetupSiteForm
from models import SiteSettings, User, db, utcnow

setup_bp = Blueprint("setup", __name__)


def _setup_is_complete():
    admin_exists = User.query.filter_by(is_admin=True).first() is not None
    setup_complete = SiteSettings.get("setup_complete", "false") == "true"
    return admin_exists and setup_complete


@setup_bp.route("/setup", methods=["GET", "POST"])
def step1():
    if _setup_is_complete():
        return redirect(url_for("public.index"))

    form = SetupAdminForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("An account with that email already exists.", "error")
            return render_template("setup/step1.html", form=form)

        user = User(
            name=form.name.data,
            email=form.email.data,
            is_admin=True,
            email_verified_at=utcnow(),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("setup.step2"))

    return render_template("setup/step1.html", form=form)


@setup_bp.route("/setup/site", methods=["GET", "POST"])
def step2():
    if _setup_is_complete():
        return redirect(url_for("public.index"))

    if User.query.filter_by(is_admin=True).first() is None:
        return redirect(url_for("setup.step1"))

    form = SetupSiteForm()
    if form.validate_on_submit():
        SiteSettings.set("site_name", form.site_name.data)
        SiteSettings.set("site_tagline", form.site_tagline.data or "")
        SiteSettings.set("contact_email", form.contact_email.data or "")
        SiteSettings.set("ui_theme", form.ui_theme.data)
        return redirect(url_for("setup.complete"))

    if not form.is_submitted():
        form.site_name.data = SiteSettings.get("site_name", "Ludus Party Planner")
        form.site_tagline.data = SiteSettings.get("site_tagline", "Board Games & LAN Parties")
        form.ui_theme.data = SiteSettings.get("ui_theme", "dark")

    return render_template("setup/step2.html", form=form)


@setup_bp.route("/setup/complete")
def complete():
    if User.query.filter_by(is_admin=True).first() is None:
        return redirect(url_for("setup.step1"))

    SiteSettings.set("setup_complete", "true")
    return render_template("setup/complete.html")
