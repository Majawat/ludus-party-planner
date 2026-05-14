from uuid import uuid4

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from forms import EventRegistrationForm
from mailer import send_registration_confirmation_email
from models import Event, Registration, Seat, TicketType, db, utcnow

account_bp = Blueprint("account", __name__)


@account_bp.route("/dashboard")
@login_required
def dashboard():
    registrations = (
        Registration.query.join(Event)
        .filter(Registration.user_id == current_user.id)
        .order_by(Event.start_datetime.desc())
        .all()
    )
    return render_template("account/dashboard.html", registrations=registrations)


@account_bp.route("/account")
@login_required
def profile():
    return render_template("account/profile.html")


@account_bp.route("/events/<slug>/register", methods=["GET", "POST"])
@login_required
def register_event(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    if not current_user.is_verified:
        flash("You must verify your email address before registering for events.", "warning")
        return redirect(url_for("public.event_detail", slug=slug))

    existing = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()
    if existing:
        flash("You are already registered for this event.", "info")
        return redirect(url_for("account.my_registration", slug=slug))

    if not event.registration_open:
        flash("Registration for this event is currently closed.", "warning")
        return redirect(url_for("public.event_detail", slug=slug))

    if event.registration_closes_at and event.registration_closes_at < utcnow():
        flash("Registration for this event has closed.", "warning")
        return redirect(url_for("public.event_detail", slug=slug))

    available_tickets = [
        t for t in event.ticket_types
        if t.is_active and t.quantity_sold < t.quantity_total
    ]
    if not available_tickets:
        flash("This event is sold out.", "warning")
        return redirect(url_for("public.event_detail", slug=slug))

    has_lodging_tickets = any(t.includes_lodging for t in event.ticket_types if t.is_active)

    form = EventRegistrationForm()
    form.ticket_type_id.choices = [
        (t.id, f"{t.name} — {'Free' if t.price == 0 else f'${t.price:.2f}'}")
        for t in available_tickets
    ]

    if form.validate_on_submit():
        ticket = TicketType.query.filter_by(
            id=form.ticket_type_id.data, event_id=event.id, is_active=True
        ).first()
        if ticket is None or ticket.quantity_sold >= ticket.quantity_total:
            flash("The selected ticket type is no longer available. Please try again.", "error")
            return redirect(url_for("account.register_event", slug=slug))

        registration = Registration(
            user_id=current_user.id,
            event_id=event.id,
            ticket_type_id=ticket.id,
            status="confirmed",
            payment_status="unpaid",
            checkin_code=str(uuid4()),
            emergency_contact_name=form.emergency_contact_name.data or None,
            emergency_contact_phone=form.emergency_contact_phone.data or None,
        )
        db.session.add(registration)
        db.session.commit()

        try:
            send_registration_confirmation_email(registration)
        except Exception:
            pass

        flash("You're registered! A confirmation email has been sent.", "success")
        return redirect(url_for("account.my_registration", slug=slug))

    return render_template(
        "account/register_event.html",
        event=event,
        form=form,
        has_lodging_tickets=has_lodging_tickets,
        available_tickets=available_tickets,
    )


@account_bp.route("/events/<slug>/my-registration")
@login_required
def my_registration(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    registration = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    return render_template(
        "account/my_registration.html",
        event=event,
        registration=registration,
    )


@account_bp.route("/events/<slug>/my-registration/cancel", methods=["POST"])
@login_required
def cancel_registration(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    registration = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    if registration.status == "cancelled":
        flash("This registration is already cancelled.", "info")
        return redirect(url_for("account.my_registration", slug=slug))

    registration.status = "cancelled"
    registration.seat_id = None
    db.session.commit()

    flash("Your registration has been cancelled.", "success")
    return redirect(url_for("account.dashboard"))


def _get_seatable_registration(slug):
    """Load published event + non-cancelled seatable registration, or return (None, None)."""
    from sqlalchemy import select as sa_select
    event = db.session.execute(
        sa_select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        return None, None
    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()
    if reg is None or reg.status == "cancelled" or not reg.ticket_type.seatable:
        return event, None
    return event, reg


@account_bp.route("/events/<slug>/seats")
@login_required
def seat_selection(slug):
    event, reg = _get_seatable_registration(slug)
    if event is None:
        abort(404)
    if reg is None:
        flash("Seat selection is only available for confirmed registrations with a seatable ticket.", "warning")
        return redirect(url_for("public.event_detail", slug=slug))
    if not event.is_upcoming:
        flash("Seat selection is closed for past events.", "warning")
        return redirect(url_for("account.my_registration", slug=slug))

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
    return render_template(
        "account/seats.html",
        event=event,
        registration=reg,
        seats=seats,
        taken_map=taken_map,
    )


@account_bp.route("/events/<slug>/seats/claim", methods=["POST"])
@login_required
def seat_claim(slug):
    event, reg = _get_seatable_registration(slug)
    if event is None:
        abort(404)
    if reg is None:
        abort(403)
    if not event.is_upcoming:
        flash("Seat selection is closed for past events.", "warning")
        return redirect(url_for("account.my_registration", slug=slug))

    try:
        seat_id = int(request.form.get("seat_id", ""))
    except (ValueError, TypeError):
        flash("Invalid seat selection.", "error")
        return redirect(url_for("account.seat_selection", slug=slug))

    seat = db.session.get(Seat, seat_id)
    if seat is None or seat.event_id != event.id:
        flash("Seat not found.", "error")
        return redirect(url_for("account.seat_selection", slug=slug))

    taken = Registration.query.filter(
        Registration.seat_id == seat.id,
        Registration.status != "cancelled",
        Registration.id != reg.id,
    ).count() > 0
    if taken:
        flash("That seat was just claimed. Please choose another.", "warning")
        return redirect(url_for("account.seat_selection", slug=slug))

    reg.seat_id = seat.id
    db.session.commit()
    flash(f"Seat '{seat.label}' claimed!", "success")
    return redirect(url_for("account.my_registration", slug=slug))


@account_bp.route("/events/<slug>/seats/release", methods=["POST"])
@login_required
def seat_release(slug):
    event, reg = _get_seatable_registration(slug)
    if event is None:
        abort(404)
    if reg is None:
        abort(403)
    reg.seat_id = None
    db.session.commit()
    flash("Seat released.", "success")
    return redirect(url_for("account.my_registration", slug=slug))


@account_bp.route("/events/<slug>/my-registration/toggle-loaner", methods=["POST"])
@login_required
def toggle_loaner(slug):
    from sqlalchemy import select as sa_select
    event = db.session.execute(
        sa_select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)
    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    if reg.status == "cancelled" or not event.is_upcoming:
        abort(403)

    reg.needs_loaner = "needs_loaner" in request.form
    db.session.commit()
    if reg.needs_loaner:
        flash("Loaner request saved.", "success")
    else:
        flash("Loaner request removed.", "success")
    return redirect(url_for("account.my_registration", slug=slug))
