import csv
import io
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from forms import (
    AdminEmailForm, AdminMarkPaidForm, AdminNotesForm, AdminSettingsForm,
    AnnouncementForm, BulkSeatForm, EventForm, EventQuestionForm, LoanerEquipmentForm,
    SeatForm, ScheduleItemForm, TicketTypeForm,
)
from models import (
    Event, EventAnnouncement, EventQuestion, EventScheduleItem, LoanerEquipment, LoanerRequest,
    Registration, RegistrationAnswer, Seat, SiteSettings, TicketType, User,
    db, slugify, unique_field_name, unique_slug,
)

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
    user_count = db.session.query(User).count()
    return render_template("admin/dashboard.html", event_count=event_count, user_count=user_count)


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


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

def _get_event_or_404(event_id):
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    return event


def _get_registration_or_404(event, rid):
    reg = db.session.get(Registration, rid)
    if reg is None or reg.event_id != event.id:
        abort(404)
    return reg


@admin_bp.route("/events/<int:id>/registrations")
def registrations_list(id):
    event = _get_event_or_404(id)

    filter_val = request.args.get("filter", "all")
    q = request.args.get("q", "").strip()

    query = (
        db.select(Registration)
        .where(Registration.event_id == event.id)
        .join(Registration.user)
        .order_by(Registration.created_at.desc())
    )

    if filter_val == "unpaid":
        query = query.where(Registration.payment_status == "unpaid", Registration.status != "cancelled")
    elif filter_val == "paid":
        query = query.where(Registration.payment_status == "paid")
    elif filter_val == "comped":
        query = query.where(Registration.payment_status == "comped")
    elif filter_val == "checked-in":
        query = query.where(Registration.checked_in_at.isnot(None))
    elif filter_val == "cancelled":
        query = query.where(Registration.status == "cancelled")
    else:
        filter_val = "all"

    if q:
        like = f"%{q}%"
        query = query.where(
            db.or_(User.name.ilike(like), User.email.ilike(like))
        )

    registrations = db.session.execute(query).scalars().all()

    if request.headers.get("HX-Request"):
        return render_template(
            "admin/events/registrations/_rows.html",
            registrations=registrations,
            event=event,
        )

    counts = {
        "all": db.session.execute(
            db.select(db.func.count(Registration.id)).where(Registration.event_id == event.id)
        ).scalar(),
        "unpaid": db.session.execute(
            db.select(db.func.count(Registration.id)).where(
                Registration.event_id == event.id,
                Registration.payment_status == "unpaid",
                Registration.status != "cancelled",
            )
        ).scalar(),
        "paid": db.session.execute(
            db.select(db.func.count(Registration.id)).where(
                Registration.event_id == event.id, Registration.payment_status == "paid"
            )
        ).scalar(),
        "comped": db.session.execute(
            db.select(db.func.count(Registration.id)).where(
                Registration.event_id == event.id, Registration.payment_status == "comped"
            )
        ).scalar(),
        "checked-in": db.session.execute(
            db.select(db.func.count(Registration.id)).where(
                Registration.event_id == event.id, Registration.checked_in_at.isnot(None)
            )
        ).scalar(),
        "cancelled": db.session.execute(
            db.select(db.func.count(Registration.id)).where(
                Registration.event_id == event.id, Registration.status == "cancelled"
            )
        ).scalar(),
    }

    return render_template(
        "admin/events/registrations/list.html",
        event=event,
        registrations=registrations,
        filter_val=filter_val,
        q=q,
        counts=counts,
    )


@admin_bp.route("/events/<int:id>/registrations/export.csv")
def registrations_export(id):
    event = _get_event_or_404(id)
    registrations = db.session.execute(
        db.select(Registration)
        .where(Registration.event_id == event.id)
        .join(Registration.user)
        .order_by(User.name)
    ).scalars().all()

    questions = event.questions  # ordered by display_order via relationship

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Email", "Ticket Type", "Status", "Payment Status",
        "Payment Method", "Paid At", "Checked In At", "Needs Loaner",
        "Emergency Contact Name", "Emergency Contact Phone", "Registered At",
        *[q.question_text for q in questions],
    ])
    for reg in registrations:
        answers_by_qid = {ans.question_id: ans.answer for ans in reg.answers}
        writer.writerow([
            reg.user.name,
            reg.user.email,
            reg.ticket_type.name,
            reg.status,
            reg.payment_status,
            reg.payment_method or "",
            reg.paid_at.strftime("%Y-%m-%d %H:%M") if reg.paid_at else "",
            reg.checked_in_at.strftime("%Y-%m-%d %H:%M") if reg.checked_in_at else "",
            "Yes" if reg.needs_loaner else "No",
            reg.emergency_contact_name or "",
            reg.emergency_contact_phone or "",
            reg.created_at.strftime("%Y-%m-%d %H:%M"),
            *[answers_by_qid.get(q.id, "") or "" for q in questions],
        ])

    filename = f"{event.slug}-registrations.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/events/<int:id>/registrations/<int:rid>")
def registration_detail(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    paid_form = AdminMarkPaidForm(prefix="paid")
    notes_form = AdminNotesForm(prefix="notes", obj=reg)
    answers_by_qid = {ans.question_id: ans.answer for ans in reg.answers}
    return render_template(
        "admin/events/registrations/detail.html",
        event=event,
        reg=reg,
        paid_form=paid_form,
        notes_form=notes_form,
        answers_by_qid=answers_by_qid,
    )


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/mark-paid", methods=["POST"])
def registration_mark_paid(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    form = AdminMarkPaidForm(prefix="paid")
    if form.validate_on_submit():
        reg.payment_status = "paid"
        reg.payment_method = form.payment_method.data
        reg.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if reg.status == "pending":
            reg.status = "confirmed"
        db.session.commit()
        flash("Marked as paid.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/mark-comped", methods=["POST"])
def registration_mark_comped(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    reg.payment_status = "comped"
    reg.payment_method = None
    reg.paid_at = None
    if reg.status == "pending":
        reg.status = "confirmed"
    db.session.commit()
    flash("Marked as comped.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/check-in", methods=["POST"])
def registration_checkin(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    reg.checked_in_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    if request.headers.get("HX-Request"):
        return render_template("admin/events/_checkin_row.html", reg=reg, event=event)
    flash("Checked in.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/undo-checkin", methods=["POST"])
def registration_undo_checkin(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    reg.checked_in_at = None
    db.session.commit()
    flash("Check-in undone.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/cancel", methods=["POST"])
def registration_cancel(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    reg.status = "cancelled"
    reg.seat_id = None
    db.session.commit()
    flash("Registration cancelled.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/notes", methods=["POST"])
def registration_notes(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    form = AdminNotesForm(prefix="notes")
    if form.validate_on_submit():
        reg.admin_notes = form.admin_notes.data or None
        db.session.commit()
        flash("Notes saved.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------

def _seat_is_taken(seat_id, exclude_registration_id=None):
    q = Registration.query.filter(
        Registration.seat_id == seat_id,
        Registration.status != "cancelled",
    )
    if exclude_registration_id:
        q = q.filter(Registration.id != exclude_registration_id)
    return q.count() > 0


@admin_bp.route("/events/<int:id>/seats")
def seats_list(id):
    event = _get_event_or_404(id)
    seats = (
        db.session.execute(
            db.select(Seat)
            .where(Seat.event_id == event.id)
            .order_by(Seat.display_order, Seat.id)
        )
        .scalars()
        .all()
    )
    taken_regs = (
        db.session.execute(
            db.select(Registration)
            .where(
                Registration.event_id == event.id,
                Registration.seat_id.isnot(None),
                Registration.status != "cancelled",
            )
        )
        .scalars()
        .all()
    )
    taken_map = {r.seat_id: r for r in taken_regs}
    seat_form = SeatForm(prefix="single")
    bulk_form = BulkSeatForm(prefix="bulk")
    return render_template(
        "admin/events/seats.html",
        event=event,
        seats=seats,
        taken_map=taken_map,
        seat_form=seat_form,
        bulk_form=bulk_form,
    )


@admin_bp.route("/events/<int:id>/seats/add", methods=["POST"])
def seat_add(id):
    event = _get_event_or_404(id)
    form = SeatForm(prefix="single")
    if form.validate_on_submit():
        seat = Seat(
            event_id=event.id,
            label=form.label.data.strip(),
            display_order=form.display_order.data or 0,
        )
        db.session.add(seat)
        db.session.commit()
        flash(f"Seat '{seat.label}' added.", "success")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{error}", "error")
    return redirect(url_for("admin.seats_list", id=event.id))


@admin_bp.route("/events/<int:id>/seats/bulk-add", methods=["POST"])
def seat_bulk_add(id):
    event = _get_event_or_404(id)
    form = BulkSeatForm(prefix="bulk")
    if form.validate_on_submit():
        prefix = form.prefix.data.strip()
        count = form.count.data
        start = form.start_number.data
        for i in range(count):
            db.session.add(Seat(
                event_id=event.id,
                label=f"{prefix} {start + i}",
                display_order=start + i,
            ))
        db.session.commit()
        flash(f"Added {count} seat(s).", "success")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{error}", "error")
    return redirect(url_for("admin.seats_list", id=event.id))


@admin_bp.route("/events/<int:id>/seats/<int:sid>/delete", methods=["POST"])
def seat_delete(id, sid):
    event = _get_event_or_404(id)
    seat = db.session.get(Seat, sid)
    if seat is None or seat.event_id != event.id:
        abort(404)
    if _seat_is_taken(seat.id):
        flash("Cannot delete a seat that is claimed by a registrant.", "error")
        return redirect(url_for("admin.seats_list", id=event.id))
    db.session.delete(seat)
    db.session.commit()
    flash(f"Seat '{seat.label}' deleted.", "success")
    return redirect(url_for("admin.seats_list", id=event.id))


@admin_bp.route("/events/<int:id>/registrations/<int:rid>/assign-seat", methods=["POST"])
def registration_assign_seat(id, rid):
    event = _get_event_or_404(id)
    reg = _get_registration_or_404(event, rid)
    seat_id_raw = request.form.get("seat_id", "").strip()

    if seat_id_raw == "" or seat_id_raw == "none":
        reg.seat_id = None
        db.session.commit()
        flash("Seat released.", "success")
        return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))

    try:
        seat_id = int(seat_id_raw)
    except ValueError:
        flash("Invalid seat.", "error")
        return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))

    seat = db.session.get(Seat, seat_id)
    if seat is None or seat.event_id != event.id:
        flash("Seat not found.", "error")
        return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))

    if _seat_is_taken(seat.id, exclude_registration_id=reg.id):
        flash("That seat is already claimed by another registrant.", "error")
        return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))

    reg.seat_id = seat.id
    db.session.commit()
    flash(f"Seat '{seat.label}' assigned.", "success")
    return redirect(url_for("admin.registration_detail", id=event.id, rid=reg.id))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@admin_bp.route("/users")
def users_list():
    q = request.args.get("q", "").strip()
    query = db.select(User).order_by(User.created_at.desc())
    if q:
        like = f"%{q}%"
        query = query.where(db.or_(User.name.ilike(like), User.email.ilike(like)))
    users = db.session.execute(query).scalars().all()

    if request.headers.get("HX-Request"):
        return render_template("admin/users/_rows.html", users=users)

    total = db.session.execute(db.select(db.func.count(User.id))).scalar()
    return render_template("admin/users/list.html", users=users, q=q, total=total)


@admin_bp.route("/users/<int:uid>")
def user_detail(uid):
    user = db.session.get(User, uid)
    if user is None:
        abort(404)
    registrations = (
        Registration.query.filter_by(user_id=user.id)
        .join(Event)
        .order_by(Event.start_datetime.desc())
        .all()
    )
    return render_template("admin/users/detail.html", user=user, registrations=registrations)


@admin_bp.route("/users/<int:uid>/toggle-admin", methods=["POST"])
def user_toggle_admin(uid):
    user = db.session.get(User, uid)
    if user is None:
        abort(404)
    from flask_login import current_user
    if user.id == current_user.id:
        flash("You cannot change your own admin status.", "error")
        return redirect(url_for("admin.user_detail", uid=uid))
    if user.is_admin:
        admin_count = db.session.execute(
            db.select(db.func.count(User.id)).where(User.is_admin == True)
        ).scalar()
        if admin_count <= 1:
            flash("Cannot remove the last admin.", "error")
            return redirect(url_for("admin.user_detail", uid=uid))
    user.is_admin = not user.is_admin
    db.session.commit()
    action = "granted admin access" if user.is_admin else "had admin access revoked"
    flash(f"{user.name} {action}.", "success")
    return redirect(url_for("admin.user_detail", uid=uid))


# ---------------------------------------------------------------------------
# Mass Email
# ---------------------------------------------------------------------------

@admin_bp.route("/email", methods=["GET", "POST"])
def email_compose():
    from mailer import send_mass_email
    events = db.session.execute(
        db.select(Event).order_by(Event.start_datetime.desc())
    ).scalars().all()

    form = AdminEmailForm()
    form.event_id.choices = [(0, "— No event / all registered users —")] + [
        (e.id, e.name) for e in events
    ]

    if form.validate_on_submit():
        event_id = form.event_id.data or 0
        recipient_filter = form.recipient_filter.data

        if event_id == 0:
            users = db.session.execute(db.select(User)).scalars().all()
        else:
            event = db.session.get(Event, event_id)
            if event is None:
                flash("Event not found.", "error")
                return redirect(url_for("admin.email_compose"))

            reg_query = db.select(Registration).where(
                Registration.event_id == event_id,
                Registration.status != "cancelled",
            )
            if recipient_filter == "paid":
                reg_query = reg_query.where(Registration.payment_status == "paid")
            elif recipient_filter == "unpaid":
                reg_query = reg_query.where(Registration.payment_status == "unpaid")
            elif recipient_filter == "comped":
                reg_query = reg_query.where(Registration.payment_status == "comped")
            elif recipient_filter == "confirmed":
                reg_query = reg_query.where(Registration.status == "confirmed")

            regs = db.session.execute(reg_query).scalars().all()
            seen = set()
            users = []
            for r in regs:
                if r.user_id not in seen:
                    seen.add(r.user_id)
                    users.append(r.user)

        success_count, failed = send_mass_email(users, form.subject.data, form.body.data)
        flash(f"Sent to {success_count} recipient(s).", "success")
        if failed:
            flash(f"Failed to deliver to: {', '.join(failed)}", "warning")

        return redirect(url_for("admin.email_compose"))

    return render_template("admin/email.html", form=form, events=events)


# ---------------------------------------------------------------------------
# Event Schedule
# ---------------------------------------------------------------------------

@admin_bp.route("/events/<int:id>/schedule")
def schedule_list(id):
    event = _get_event_or_404(id)
    form = ScheduleItemForm()
    return render_template("admin/events/schedule.html", event=event, form=form)


@admin_bp.route("/events/<int:id>/schedule/add", methods=["POST"])
def schedule_add(id):
    event = _get_event_or_404(id)
    form = ScheduleItemForm()
    if form.validate_on_submit():
        item = EventScheduleItem(
            event_id=event.id,
            title=form.title.data,
            description=form.description.data or None,
            starts_at=form.starts_at.data,
            ends_at=form.ends_at.data or None,
            display_order=form.display_order.data or 0,
        )
        db.session.add(item)
        db.session.commit()
        if request.headers.get("HX-Request"):
            return render_template("admin/events/_schedule_row.html", item=item, event=event)
        flash("Schedule item added.", "success")
    else:
        for errors in form.errors.values():
            for error in errors:
                flash(error, "error")
    return redirect(url_for("admin.schedule_list", id=event.id))


@admin_bp.route("/events/<int:id>/schedule/<int:item_id>/delete", methods=["POST"])
def schedule_delete(id, item_id):
    event = _get_event_or_404(id)
    item = db.session.get(EventScheduleItem, item_id)
    if item is None or item.event_id != event.id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    if request.headers.get("HX-Request"):
        return "", 200
    flash("Schedule item deleted.", "success")
    return redirect(url_for("admin.schedule_list", id=event.id))


# ---------------------------------------------------------------------------
# Event Announcements
# ---------------------------------------------------------------------------

@admin_bp.route("/events/<int:id>/announcements/add", methods=["POST"])
def announcement_add(id):
    event = _get_event_or_404(id)
    form = AnnouncementForm()
    if form.validate_on_submit():
        ann = EventAnnouncement(
            event_id=event.id,
            title=form.title.data,
            body=form.body.data,
            created_by=current_user.id,
        )
        db.session.add(ann)
        db.session.commit()
        flash("Announcement posted.", "success")
    else:
        for errors in form.errors.values():
            for error in errors:
                flash(error, "error")
    return redirect(url_for("admin.event_detail", id=event.id))


@admin_bp.route("/events/<int:id>/announcements/<int:ann_id>/delete", methods=["POST"])
def announcement_delete(id, ann_id):
    event = _get_event_or_404(id)
    ann = db.session.get(EventAnnouncement, ann_id)
    if ann is None or ann.event_id != event.id:
        abort(404)
    db.session.delete(ann)
    db.session.commit()
    flash("Announcement deleted.", "success")
    return redirect(url_for("admin.event_detail", id=event.id))


# ---------------------------------------------------------------------------
# Loaner Equipment
# ---------------------------------------------------------------------------

@admin_bp.route("/equipment")
def equipment_list():
    equipment = db.session.execute(
        db.select(LoanerEquipment).order_by(LoanerEquipment.name)
    ).scalars().all()
    form = LoanerEquipmentForm()
    form.is_available.data = True
    return render_template("admin/equipment.html", equipment=equipment, form=form)


@admin_bp.route("/equipment/add", methods=["POST"])
def equipment_add():
    form = LoanerEquipmentForm()
    if form.validate_on_submit():
        eq = LoanerEquipment(
            name=form.name.data,
            description=form.description.data or None,
            specs=form.specs.data or None,
            is_available=form.is_available.data,
        )
        db.session.add(eq)
        db.session.commit()
        flash(f"Equipment '{eq.name}' added.", "success")
    else:
        for errors in form.errors.values():
            for error in errors:
                flash(error, "error")
    return redirect(url_for("admin.equipment_list"))


@admin_bp.route("/equipment/<int:eid>/edit", methods=["POST"])
def equipment_edit(eid):
    eq = db.session.get(LoanerEquipment, eid)
    if eq is None:
        abort(404)
    form = LoanerEquipmentForm()
    if form.validate_on_submit():
        eq.name = form.name.data
        eq.description = form.description.data or None
        eq.specs = form.specs.data or None
        eq.is_available = form.is_available.data
        db.session.commit()
        flash("Equipment updated.", "success")
    else:
        for errors in form.errors.values():
            for error in errors:
                flash(error, "error")
    return redirect(url_for("admin.equipment_list"))


@admin_bp.route("/equipment/<int:eid>/toggle", methods=["POST"])
def equipment_toggle(eid):
    eq = db.session.get(LoanerEquipment, eid)
    if eq is None:
        abort(404)
    eq.is_available = not eq.is_available
    db.session.commit()
    status = "available" if eq.is_available else "unavailable"
    flash(f"'{eq.name}' marked as {status}.", "success")
    return redirect(url_for("admin.equipment_list"))


@admin_bp.route("/events/<int:id>/loaners")
def loaners_list(id):
    event = _get_event_or_404(id)
    requests = (
        db.session.execute(
            db.select(LoanerRequest)
            .join(LoanerRequest.registration)
            .where(Registration.event_id == event.id)
            .order_by(LoanerRequest.created_at)
        )
        .scalars()
        .all()
    )
    return render_template("admin/events/loaners.html", event=event, requests=requests)


@admin_bp.route("/events/<int:id>/loaners/<int:req_id>/approve", methods=["POST"])
def loaner_approve(id, req_id):
    event = _get_event_or_404(id)
    req_obj = db.session.get(LoanerRequest, req_id)
    if req_obj is None or req_obj.registration.event_id != event.id:
        abort(404)
    req_obj.status = "approved"
    db.session.commit()
    flash("Loaner request approved.", "success")
    return redirect(url_for("admin.loaners_list", id=event.id))


@admin_bp.route("/events/<int:id>/loaners/<int:req_id>/deny", methods=["POST"])
def loaner_deny(id, req_id):
    event = _get_event_or_404(id)
    req_obj = db.session.get(LoanerRequest, req_id)
    if req_obj is None or req_obj.registration.event_id != event.id:
        abort(404)
    req_obj.status = "denied"
    db.session.commit()
    flash("Loaner request denied.", "success")
    return redirect(url_for("admin.loaners_list", id=event.id))


# ---------------------------------------------------------------------------
# Check-in Mode
# ---------------------------------------------------------------------------

@admin_bp.route("/events/<int:id>/checkin")
def checkin_mode(id):
    event = _get_event_or_404(id)
    return render_template("admin/events/checkin.html", event=event)


@admin_bp.route("/events/<int:id>/checkin/search")
def checkin_search(id):
    event = _get_event_or_404(id)
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("admin/events/_checkin_rows.html", registrations=[], event=event)
    like = f"%{q}%"
    registrations = (
        db.session.execute(
            db.select(Registration)
            .where(Registration.event_id == event.id)
            .join(Registration.user)
            .where(db.or_(User.name.ilike(like), User.email.ilike(like)))
            .where(Registration.status != "cancelled")
            .order_by(User.name)
        )
        .scalars()
        .all()
    )
    return render_template("admin/events/_checkin_rows.html", registrations=registrations, event=event)


# ---------------------------------------------------------------------------
# Custom Questions
# ---------------------------------------------------------------------------

@admin_bp.route("/events/<int:id>/questions")
def questions_list(id):
    event = _get_event_or_404(id)
    form = EventQuestionForm()
    questions_with_counts = []
    for q in event.questions:
        count = db.session.execute(
            db.select(db.func.count(RegistrationAnswer.id)).where(RegistrationAnswer.question_id == q.id)
        ).scalar()
        questions_with_counts.append((q, count))
    return render_template(
        "admin/events/questions.html",
        event=event,
        questions_with_counts=questions_with_counts,
        form=form,
    )


@admin_bp.route("/events/<int:id>/questions/add", methods=["POST"])
def question_add(id):
    event = _get_event_or_404(id)
    form = EventQuestionForm()
    if form.validate_on_submit():
        field_name = unique_field_name(form.question_text.data, event.id)
        options = None
        if form.question_type.data == "select":
            raw = form.options.data or ""
            opts = [o.strip() for o in raw.splitlines() if o.strip()]
            if opts:
                options = json.dumps(opts)
        q = EventQuestion(
            event_id=event.id,
            question_text=form.question_text.data,
            question_type=form.question_type.data,
            field_name=field_name,
            is_required=form.is_required.data,
            display_order=form.display_order.data or 0,
            options=options,
        )
        db.session.add(q)
        db.session.commit()
        if request.headers.get("HX-Request"):
            return render_template("admin/events/_question_row.html", q=q, event=event, answer_count=0)
        flash("Question added.", "success")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", "error")
    return redirect(url_for("admin.questions_list", id=event.id))


@admin_bp.route("/events/<int:id>/questions/<int:qid>/edit", methods=["GET", "POST"])
def question_edit(id, qid):
    event = _get_event_or_404(id)
    q = db.session.get(EventQuestion, qid)
    if q is None or q.event_id != event.id:
        abort(404)

    has_answers = db.session.execute(
        db.select(db.func.count(RegistrationAnswer.id)).where(RegistrationAnswer.question_id == q.id)
    ).scalar() > 0

    if request.method == "POST":
        form = EventQuestionForm()
        if form.validate_on_submit():
            if has_answers and form.question_type.data != q.question_type:
                flash("Cannot change question type when answers already exist.", "error")
                options_text = "\n".join(q.options_list)
                return render_template(
                    "admin/events/question_edit.html",
                    event=event, q=q, form=form,
                    has_answers=has_answers, options_text=options_text,
                )
            options = None
            if form.question_type.data == "select":
                raw = form.options.data or ""
                opts = [o.strip() for o in raw.splitlines() if o.strip()]
                if opts:
                    options = json.dumps(opts)
            q.question_text = form.question_text.data
            q.question_type = form.question_type.data
            q.is_required = form.is_required.data
            q.display_order = form.display_order.data or 0
            q.options = options
            db.session.commit()
            flash("Question updated.", "success")
            return redirect(url_for("admin.questions_list", id=event.id))
    else:
        form = EventQuestionForm(obj=q)
        form.options.data = "\n".join(q.options_list)

    options_text = "\n".join(q.options_list)
    return render_template(
        "admin/events/question_edit.html",
        event=event, q=q, form=form,
        has_answers=has_answers, options_text=options_text,
    )


@admin_bp.route("/events/<int:id>/questions/<int:qid>/delete", methods=["POST"])
def question_delete(id, qid):
    event = _get_event_or_404(id)
    q = db.session.get(EventQuestion, qid)
    if q is None or q.event_id != event.id:
        abort(404)

    count = db.session.execute(
        db.select(db.func.count(RegistrationAnswer.id)).where(RegistrationAnswer.question_id == q.id)
    ).scalar()
    if count > 0:
        flash(f"Cannot delete: this question has {count} answer(s). Remove all registrations first.", "error")
        return redirect(url_for("admin.questions_list", id=event.id))

    db.session.delete(q)
    db.session.commit()
    if request.headers.get("HX-Request"):
        return "", 200
    flash("Question deleted.", "success")
    return redirect(url_for("admin.questions_list", id=event.id))
