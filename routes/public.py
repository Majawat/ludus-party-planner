from flask import Blueprint, render_template, abort
from flask_login import current_user
from sqlalchemy import select

from models import db, Event, EventAnnouncement, EventScheduleItem, PotluckItem, Registration, SiteSettings, utcnow

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

    attendees = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status != "cancelled",
    ).all()

    user_registration = None
    if current_user.is_authenticated:
        user_registration = Registration.query.filter_by(
            user_id=current_user.id, event_id=event.id
        ).first()

    registration_is_open = (
        event.registration_open
        and (event.registration_closes_at is None or event.registration_closes_at > utcnow())
        and event.is_upcoming
    )

    schedule_items = (
        db.session.execute(
            db.select(EventScheduleItem)
            .where(EventScheduleItem.event_id == event.id)
            .order_by(EventScheduleItem.starts_at)
        )
        .scalars()
        .all()
    )

    potluck_items = (
        db.session.execute(
            db.select(PotluckItem)
            .where(PotluckItem.event_id == event.id)
            .join(PotluckItem.registration)
            .where(Registration.status != "cancelled")
            .order_by(PotluckItem.created_at)
        )
        .scalars()
        .all()
    )

    announcements = (
        db.session.execute(
            db.select(EventAnnouncement)
            .where(EventAnnouncement.event_id == event.id)
            .order_by(EventAnnouncement.created_at.desc())
        )
        .scalars()
        .all()
    )

    return render_template(
        "public/event_detail.html",
        event=event,
        attendees=attendees,
        user_registration=user_registration,
        registration_is_open=registration_is_open,
        schedule_items=schedule_items,
        potluck_items=potluck_items,
        announcements=announcements,
    )
