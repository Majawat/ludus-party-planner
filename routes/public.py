from flask import Blueprint, render_template, abort
from sqlalchemy import select

from models import db, Event, SiteSettings, utcnow

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def index():
    upcoming_event = None
    if SiteSettings.get("show_upcoming_event_on_homepage", "true") == "true":
        upcoming_event = db.session.execute(
            select(Event)
            .filter_by(status="published")
            .where(Event.start_datetime > utcnow())
            .order_by(Event.start_datetime.asc())
            .limit(1)
        ).scalar_one_or_none()
    return render_template("public/index.html", upcoming_event=upcoming_event)


@public_bp.route("/events")
def events():
    all_events = db.session.execute(
        select(Event)
        .filter_by(status="published")
        .order_by(Event.start_datetime.desc())
    ).scalars().all()
    return render_template("public/events.html", events=all_events)


@public_bp.route("/events/<slug>")
def event_detail(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)
    return render_template("public/event_detail.html", event=event)
