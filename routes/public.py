from flask import Blueprint, render_template

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def index():
    return render_template("public/index.html")


@public_bp.route("/events")
def events():
    return render_template("public/events.html")


@public_bp.route("/events/<slug>")
def event_detail(slug):
    return render_template("public/event_detail.html", slug=slug)
