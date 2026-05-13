import json
from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from forms import AdminSettingsForm, EventForm, TicketTypeForm
from models import Event, SiteSettings, TicketType, db, slugify, unique_slug

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

_BOOL_SETTINGS = {"registration_enabled", "show_upcoming_event_on_homepage"}


@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.url))
    if not current_user.is_admin:
        abort(403)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@admin_bp.route("/")
def dashboard():
    event_count = db.session.query(Event).count()
    return render_template("admin/dashboard.html", event_count=event_count)


# ---------------------------------------------------------------------------
# Site Settings
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@admin_bp.route("/events")
def events_list():
    events = db.session.execute(
        db.select(Event).order_by(Event.created_at.desc())
    ).scalars().all()
    return render_template("admin/events/list.html", events=events)


@admin_bp.route("/events/new", methods=["GET", "POST"])
def event_new():
    form = EventForm()
    if form.validate_on_submit():
        raw_slug = form.slug.data.strip() if form.slug.data else ""
        base = slugify(raw_slug) if raw_slug else slugify(form.name.data)
        slug = unique_slug(base)
        event = Event(
            name=form.name.data,
            slug=slug,
            type=form.type.data,
            status=form.status.data,
            short_description=form.short_description.data or None,
            description=form.description.data or None,
            start_datetime=form.start_datetime.data,
            end_datetime=form.end_datetime.data,
            location=form.location.data,
            cover_image_url=form.cover_image_url.data or None,
            gallery_url=form.gallery_url.data or None,
            seating_enabled=form.seating_enabled.data,
            registration_open=form.registration_open.data,
            registration_closes_at=form.registration_closes_at.data or None,
        )
        db.session.add(event)
        db.session.commit()
        flash(f"Event '{event.name}' created.", "success")
        return redirect(url_for("admin.event_detail", id=event.id))
    return render_template("admin/events/edit.html", form=form, event=None)


@admin_bp.route("/events/<int:id>")
def event_detail(id):
    event = db.session.get(Event, id)
    if event is None:
        abort(404)
    return render_template("admin/events/detail.html", event=event)


@admin_bp.route("/events/<int:id>/edit", methods=["GET", "POST"])
def event_edit(id):
    event = db.session.get(Event, id)
    if event is None:
        abort(404)
    form = EventForm(obj=event)
    if form.validate_on_submit():
        raw_slug = form.slug.data.strip() if form.slug.data else ""
        base = slugify(raw_slug) if raw_slug else event.slug
        slug = unique_slug(base, exclude_id=event.id)
        event.name = form.name.data
        event.slug = slug
        event.type = form.type.data
        event.status = form.status.data
        event.short_description = form.short_description.data or None
        event.description = form.description.data or None
        event.start_datetime = form.start_datetime.data
        event.end_datetime = form.end_datetime.data
        event.location = form.location.data
        event.cover_image_url = form.cover_image_url.data or None
        event.gallery_url = form.gallery_url.data or None
        event.seating_enabled = form.seating_enabled.data
        event.registration_open = form.registration_open.data
        event.registration_closes_at = form.registration_closes_at.data or None
        db.session.commit()
        flash("Event updated.", "success")
        return redirect(url_for("admin.event_detail", id=event.id))
    return render_template("admin/events/edit.html", form=form, event=event)


@admin_bp.route("/events/<int:id>/clone", methods=["POST"])
def event_clone(id):
    original = db.session.get(Event, id)
    if original is None:
        abort(404)
    base = slugify(f"copy-of-{original.name}")
    clone = Event(
        name=f"Copy of {original.name}",
        slug=unique_slug(base),
        type=original.type,
        status="draft",
        short_description=original.short_description,
        description=original.description,
        start_datetime=original.start_datetime,
        end_datetime=original.end_datetime,
        location=original.location,
        cover_image_url=original.cover_image_url,
        gallery_url=original.gallery_url,
        seating_enabled=original.seating_enabled,
        registration_open=original.registration_open,
        registration_closes_at=original.registration_closes_at,
    )
    db.session.add(clone)
    db.session.flush()  # get clone.id before copying ticket types
    for tt in original.ticket_types:
        db.session.add(TicketType(
            event_id=clone.id,
            name=tt.name,
            description=tt.description,
            price=tt.price,
            quantity_total=tt.quantity_total,
            seatable=tt.seatable,
            includes_lodging=tt.includes_lodging,
            valid_days=tt.valid_days,
            max_per_user=tt.max_per_user,
            is_active=tt.is_active,
        ))
    db.session.commit()
    flash(f"Event cloned as '{clone.name}'.", "success")
    return redirect(url_for("admin.event_edit", id=clone.id))


@admin_bp.route("/events/<int:id>/toggle-status", methods=["POST"])
def event_toggle_status(id):
    event = db.session.get(Event, id)
    if event is None:
        abort(404)
    new_status = request.form.get("status")
    if new_status not in ("draft", "published", "archived"):
        abort(400)
    event.status = new_status
    db.session.commit()
    return render_template("admin/events/_status_badge.html", event=event)


# ---------------------------------------------------------------------------
# Ticket Types
# ---------------------------------------------------------------------------

def _date_range(start_dt, end_dt):
    days, current = [], start_dt.date()
    while current <= end_dt.date():
        days.append(current)
        current += timedelta(days=1)
    return days


@admin_bp.route("/events/<int:id>/tickets")
def tickets_list(id):
    event = db.session.get(Event, id)
    if event is None:
        abort(404)
    return render_template("admin/events/tickets.html", event=event)


@admin_bp.route("/events/<int:id>/tickets/new", methods=["GET", "POST"])
def ticket_new(id):
    event = db.session.get(Event, id)
    if event is None:
        abort(404)
    form = TicketTypeForm()
    available_days = _date_range(event.start_datetime, event.end_datetime)
    if form.validate_on_submit():
        selected_days = request.form.getlist("valid_days")
        if not selected_days:
            flash("Please select at least one valid day.", "error")
            return render_template(
                "admin/events/ticket_edit.html",
                form=form, event=event, ticket=None,
                available_days=available_days, selected_days=[],
            )
        ticket = TicketType(
            event_id=event.id,
            name=form.name.data,
            description=form.description.data or None,
            price=form.price.data or 0,
            quantity_total=form.quantity_total.data,
            seatable=form.seatable.data,
            includes_lodging=form.includes_lodging.data,
            valid_days=json.dumps(sorted(selected_days)),
            max_per_user=form.max_per_user.data,
            is_active=form.is_active.data,
        )
        db.session.add(ticket)
        db.session.commit()
        flash(f"Ticket type '{ticket.name}' created.", "success")
        return redirect(url_for("admin.tickets_list", id=event.id))
    return render_template(
        "admin/events/ticket_edit.html",
        form=form, event=event, ticket=None,
        available_days=available_days, selected_days=[],
    )


@admin_bp.route("/events/<int:id>/tickets/<int:tid>/edit", methods=["GET", "POST"])
def ticket_edit(id, tid):
    event = db.session.get(Event, id)
    if event is None:
        abort(404)
    ticket = db.session.get(TicketType, tid)
    if ticket is None or ticket.event_id != event.id:
        abort(404)
    form = TicketTypeForm(obj=ticket)
    available_days = _date_range(event.start_datetime, event.end_datetime)
    try:
        current_selected = json.loads(ticket.valid_days)
    except (ValueError, TypeError):
        current_selected = []
    if form.validate_on_submit():
        selected_days = request.form.getlist("valid_days")
        if not selected_days:
            flash("Please select at least one valid day.", "error")
            return render_template(
                "admin/events/ticket_edit.html",
                form=form, event=event, ticket=ticket,
                available_days=available_days, selected_days=current_selected,
            )
        ticket.name = form.name.data
        ticket.description = form.description.data or None
        ticket.price = form.price.data or 0
        ticket.quantity_total = form.quantity_total.data
        ticket.seatable = form.seatable.data
        ticket.includes_lodging = form.includes_lodging.data
        ticket.valid_days = json.dumps(sorted(selected_days))
        ticket.max_per_user = form.max_per_user.data
        ticket.is_active = form.is_active.data
        db.session.commit()
        flash("Ticket type updated.", "success")
        return redirect(url_for("admin.tickets_list", id=event.id))
    return render_template(
        "admin/events/ticket_edit.html",
        form=form, event=event, ticket=ticket,
        available_days=available_days, selected_days=current_selected,
    )
