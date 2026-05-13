from uuid import uuid4

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from forms import EventRegistrationForm
from mailer import send_registration_confirmation_email
from models import Event, Registration, TicketType, db, utcnow

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
