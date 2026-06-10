import json
from uuid import uuid4

import requests as http_requests
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

import challonge
from extensions import csrf
from forms import ChangePasswordForm, EventRegistrationForm, PotluckItemForm, SetPasswordForm
from mailer import send_registration_confirmation_email, send_registration_pending_payment_email
from models import Event, EventQuestion, LoanerEquipment, LoanerRequest, PotluckItem, Registration, RegistrationAnswer, Seat, SiteSettings, TicketType, Tournament, TournamentParticipant, UserPlatformAccount, db, get_allowed_themes, utcnow
from payments import (
    capture_paypal_order,
    create_paypal_order,
    create_stripe_session,
    retrieve_stripe_session,
    verify_paypal_webhook,
    _get_paypal_checkout_base_url,
)
from totp import (
    generate_totp_secret, get_totp_uri, verify_totp_code,
    generate_backup_codes, qr_code_data_uri,
)

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
    settings = SiteSettings.all_as_dict()
    configured_providers = []
    if settings.get("discord_oauth_client_id") and settings.get("discord_oauth_client_secret"):
        configured_providers.append("discord")
    if settings.get("google_oauth_client_id") and settings.get("google_oauth_client_secret"):
        configured_providers.append("google")
    steam_enabled = settings.get("steam_enabled") == "true"
    passkeys_enabled = settings.get("passkeys_enabled") == "true"
    connected = {acct.platform: acct for acct in current_user.platform_accounts}
    set_password_form = SetPasswordForm() if not current_user.has_password else None
    change_password_form = ChangePasswordForm() if current_user.has_password else None
    allowed_themes = get_allowed_themes()
    return render_template(
        "account/profile.html",
        configured_providers=configured_providers,
        steam_enabled=steam_enabled,
        passkeys_enabled=passkeys_enabled,
        connected=connected,
        set_password_form=set_password_form,
        change_password_form=change_password_form,
        allowed_themes=allowed_themes,
    )


@account_bp.route("/account/theme", methods=["POST"])
@login_required
def set_theme():
    theme = request.form.get("theme", "").strip()
    if not theme or theme == "default":
        current_user.preferred_theme = None
        db.session.commit()
        flash("Theme preference cleared.", "success")
        return redirect(url_for("account.profile"))
    allowed = get_allowed_themes()
    if theme not in allowed:
        flash("Invalid theme selection.", "error")
        return redirect(url_for("account.profile"))
    current_user.preferred_theme = theme
    db.session.commit()
    flash("Theme preference saved.", "success")
    return redirect(url_for("account.profile"))


@account_bp.route("/account/set-password", methods=["POST"])
@login_required
def set_password():
    if current_user.has_password:
        from flask import abort
        abort(403)
    form = SetPasswordForm()
    if form.validate_on_submit():
        current_user.set_password(form.password.data)
        db.session.commit()
        flash("Password set successfully. You can now log in with email and password.", "success")
    else:
        for field in form:
            for error in field.errors:
                flash(error, "error")
    return redirect(url_for("account.profile"))


@account_bp.route("/account/change-password", methods=["POST"])
@login_required
def change_password():
    if not current_user.has_password:
        from flask import abort
        abort(403)
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("account.profile"))
        current_user.set_password(form.new_password.data)
        db.session.commit()
        flash("Password changed successfully.", "success")
    else:
        for field in form:
            for error in field.errors:
                flash(error, "error")
    return redirect(url_for("account.profile"))


@account_bp.route("/account/connect/<provider>", methods=["POST"])
@login_required
def connect_provider(provider):
    from flask import session, abort
    # NOTE: this set mirrors _VALID_PROVIDERS in routes/auth.py — keep in sync
    if provider not in {"discord", "google"}:
        abort(404)
    settings = SiteSettings.all_as_dict()
    if not (settings.get(f"{provider}_oauth_client_id") and settings.get(f"{provider}_oauth_client_secret")):
        abort(404)
    session["oauth_connecting"] = True
    return redirect(url_for("auth.oauth_login", provider=provider))


@account_bp.route("/account/disconnect/<provider>", methods=["POST"])
@login_required
def disconnect_provider(provider):
    # NOTE: this set mirrors _VALID_PROVIDERS in routes/auth.py — keep in sync
    if provider not in {"discord", "google"}:
        abort(404)
    acct = UserPlatformAccount.query.filter_by(
        user_id=current_user.id, platform=provider
    ).first()
    if acct is None:
        flash(f"No {provider.capitalize()} account is connected.", "info")
        return redirect(url_for("account.profile"))
    if not current_user.has_password:
        linked_count = UserPlatformAccount.query.filter_by(user_id=current_user.id).count()
        if linked_count <= 1:
            flash(
                "You must set a password before disconnecting your last login method.",
                "error",
            )
            return redirect(url_for("account.profile"))
    db.session.delete(acct)
    db.session.commit()
    flash(f"{provider.capitalize()} account disconnected.", "success")
    return redirect(url_for("account.profile"))


@account_bp.route("/account/connect/steam", methods=["POST"])
@login_required
def connect_steam():
    from flask import session
    if SiteSettings.get("steam_enabled") != "true":
        abort(404)
    session["steam_connecting"] = True
    return redirect(url_for("auth.steam_login"))


@account_bp.route("/account/disconnect/steam", methods=["POST"])
@login_required
def disconnect_steam():
    acct = UserPlatformAccount.query.filter_by(
        user_id=current_user.id, platform="steam"
    ).first()
    if acct is None:
        flash("No Steam account is connected.", "info")
        return redirect(url_for("account.profile"))
    if not current_user.has_password:
        linked_count = UserPlatformAccount.query.filter_by(user_id=current_user.id).count()
        if linked_count <= 1:
            flash(
                "You must set a password before disconnecting your last login method.",
                "error",
            )
            return redirect(url_for("account.profile"))
    db.session.delete(acct)
    db.session.commit()
    flash("Steam account disconnected.", "success")
    return redirect(url_for("account.profile"))


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

    if SiteSettings.get("registration_enabled", "true") != "true":
        flash("Registration is currently disabled.", "warning")
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
    stripe_enabled = SiteSettings.get("stripe_enabled") == "true"
    paypal_enabled = SiteSettings.get("paypal_enabled") == "true"

    form = EventRegistrationForm()
    form.ticket_type_id.choices = [
        (t.id, f"{t.name} — {'Free' if t.price == 0 else f'${t.price:.2f}'}")
        for t in available_tickets
    ]

    questions = event.questions

    if form.validate_on_submit():
        ticket = TicketType.query.filter_by(
            id=form.ticket_type_id.data, event_id=event.id, is_active=True
        ).first()
        if ticket is None or ticket.quantity_sold >= ticket.quantity_total:
            flash("The selected ticket type is no longer available. Please try again.", "error")
            return redirect(url_for("account.register_event", slug=slug))

        # Validate required custom questions (boolean is always "answered" — unchecked = false)
        for q in questions:
            if q.is_required and q.question_type != "boolean":
                val = request.form.get(q.field_name, "").strip()
                if not val:
                    flash(f'"{q.question_text}" is required.', "error")
                    return render_template(
                        "account/register_event.html",
                        event=event,
                        form=form,
                        has_lodging_tickets=has_lodging_tickets,
                        available_tickets=available_tickets,
                        questions=questions,
                        form_data=request.form,
                        stripe_enabled=stripe_enabled,
                        paypal_enabled=paypal_enabled,
                    )

        # Determine payment path
        is_free = (ticket.price == 0)
        payment_choice = request.form.get("payment_choice", "later")
        if is_free:
            payment_choice = "later"
        if payment_choice == "stripe" and not stripe_enabled:
            payment_choice = "later"
        if payment_choice == "paypal" and not paypal_enabled:
            payment_choice = "later"

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
        db.session.flush()  # get registration.id before creating answers and payment calls

        for q in questions:
            if q.question_type == "boolean":
                val = "true" if request.form.get(q.field_name) else "false"
                db.session.add(RegistrationAnswer(
                    registration_id=registration.id,
                    question_id=q.id,
                    answer=val,
                ))
            else:
                val = request.form.get(q.field_name, "").strip()
                if val:
                    db.session.add(RegistrationAnswer(
                        registration_id=registration.id,
                        question_id=q.id,
                        answer=val,
                    ))

        if payment_choice == "stripe":
            try:
                # Build success_url via concatenation — url_for would percent-encode the braces
                success_url = (
                    url_for("account.stripe_success", _external=True)
                    + "?session_id={CHECKOUT_SESSION_ID}"
                )
                cancel_url = url_for("account.register_event", slug=slug, _external=True)
                session_id, checkout_url = create_stripe_session(
                    registration, event, ticket, success_url, cancel_url,
                    customer_email=registration.user.email,
                )
                registration.stripe_session_id = session_id
                registration.payment_processor = "stripe"
                db.session.commit()
                try:
                    send_registration_pending_payment_email(registration)
                except Exception:
                    pass
                return redirect(checkout_url)
            except Exception as e:
                current_app.logger.warning(f"Stripe checkout creation failed: {e}")
                db.session.rollback()
                flash("Could not create Stripe checkout. Please try again or pay later.", "error")
                return redirect(url_for("account.register_event", slug=slug))

        elif payment_choice == "paypal":
            try:
                return_url = url_for("account.paypal_success", _external=True)
                cancel_url = url_for("account.register_event", slug=slug, _external=True)
                order_id, approve_url = create_paypal_order(
                    registration, event, ticket, return_url, cancel_url
                )
                registration.paypal_order_id = order_id
                registration.payment_processor = "paypal"
                db.session.commit()
                try:
                    send_registration_pending_payment_email(registration)
                except Exception:
                    pass
                return redirect(approve_url)
            except Exception as e:
                current_app.logger.warning(f"PayPal order creation failed: {e}")
                db.session.rollback()
                flash("Could not create PayPal order. Please try again or pay later.", "error")
                return redirect(url_for("account.register_event", slug=slug))

        else:
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
        questions=questions,
        form_data=None,
        stripe_enabled=stripe_enabled,
        paypal_enabled=paypal_enabled,
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

    available_equipment = (
        LoanerEquipment.query.filter_by(is_available=True).order_by(LoanerEquipment.name).all()
        if event.is_upcoming and registration.status != "cancelled"
        else []
    )

    answers_by_qid = {ans.question_id: ans.answer for ans in registration.answers}

    stripe_session = None
    paypal_checkout_url = None
    if registration.payment_status == "unpaid" and registration.status != "cancelled":
        if registration.stripe_session_id and SiteSettings.get("stripe_enabled") == "true":
            stripe_session = retrieve_stripe_session(registration.stripe_session_id)
        if registration.paypal_order_id and SiteSettings.get("paypal_enabled") == "true":
            paypal_checkout_url = (
                _get_paypal_checkout_base_url()
                + f"/checkoutnow?token={registration.paypal_order_id}"
            )

    tournaments = Tournament.query.filter_by(event_id=event.id).all()
    participant_tournament_ids = {
        p.tournament_id for p in registration.tournament_participations
    }

    return render_template(
        "account/my_registration.html",
        event=event,
        registration=registration,
        available_equipment=available_equipment,
        questions=event.questions,
        answers_by_qid=answers_by_qid,
        stripe_session=stripe_session,
        paypal_checkout_url=paypal_checkout_url,
        tournaments=tournaments,
        participant_tournament_ids=participant_tournament_ids,
    )


@account_bp.route("/events/<slug>/my-registration/answers", methods=["POST"])
@login_required
def update_answers(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    registration = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    if not event.is_upcoming or registration.status == "cancelled":
        flash("Answers cannot be updated for this registration.", "warning")
        return redirect(url_for("account.my_registration", slug=slug))

    questions = event.questions

    # Validate required questions
    for q in questions:
        if q.is_required and q.question_type != "boolean":
            val = request.form.get(q.field_name, "").strip()
            if not val:
                flash(f'"{q.question_text}" is required.', "error")
                return redirect(url_for("account.my_registration", slug=slug))

    existing_answers = {ans.question_id: ans for ans in registration.answers}
    for q in questions:
        if q.question_type == "boolean":
            val = "true" if request.form.get(q.field_name) else "false"
            if q.id in existing_answers:
                existing_answers[q.id].answer = val
            else:
                db.session.add(RegistrationAnswer(
                    registration_id=registration.id,
                    question_id=q.id,
                    answer=val,
                ))
        else:
            val = request.form.get(q.field_name, "").strip()
            if q.id in existing_answers:
                existing_answers[q.id].answer = val if val else None
            elif val:
                db.session.add(RegistrationAnswer(
                    registration_id=registration.id,
                    question_id=q.id,
                    answer=val,
                ))

    db.session.commit()
    flash("Your answers have been updated.", "success")
    return redirect(url_for("account.my_registration", slug=slug))


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


@account_bp.route("/account/stripe/success")
@login_required
def stripe_success():
    # GET is required by Stripe: the return_url is a redirect from Stripe's
    # hosted checkout. The DB write here is a fallback confirmation — the primary
    # update path is the stripe_webhook route. Idempotent: skipped if already paid.
    session_id = request.args.get("session_id", "")
    stripe_session = retrieve_stripe_session(session_id)
    if not stripe_session:
        flash("Could not retrieve payment session.", "error")
        return redirect(url_for("account.dashboard"))

    reg_id = stripe_session.metadata.get("registration_id")
    registration = db.session.get(Registration, int(reg_id)) if reg_id else None
    if registration is None:
        flash("Registration not found.", "error")
        return redirect(url_for("account.dashboard"))
    if registration.user_id != current_user.id:
        abort(403)
    if registration.payment_status == "paid":
        return redirect(url_for("account.my_registration", slug=registration.event.slug))

    if stripe_session.payment_status == "paid":
        registration.payment_status = "paid"
        registration.payment_method = "stripe"
        registration.paid_at = utcnow()
        db.session.commit()
        flash("Payment complete! You're confirmed.", "success")
    else:
        flash("Payment not completed. You can try again from your registration page.", "warning")

    return redirect(url_for("account.my_registration", slug=registration.event.slug))


@account_bp.route("/account/paypal/success")
@login_required
def paypal_success():
    # GET is required by PayPal: the return_url is a redirect from PayPal's
    # hosted approval page. The DB write is idempotent — skipped if already paid.
    order_id = request.args.get("token", "")
    registration = Registration.query.filter_by(paypal_order_id=order_id).first()
    if registration is None:
        flash("Registration not found.", "error")
        return redirect(url_for("account.dashboard"))
    if registration.user_id != current_user.id:
        abort(403)
    if registration.payment_status == "paid":
        return redirect(url_for("account.my_registration", slug=registration.event.slug))

    if capture_paypal_order(order_id):
        registration.payment_status = "paid"
        registration.payment_method = "paypal"
        registration.paid_at = utcnow()
        db.session.commit()
        flash("Payment complete! You're confirmed.", "success")
    else:
        flash("Payment capture failed. Please contact the organizer.", "error")

    return redirect(url_for("account.my_registration", slug=registration.event.slug))


@account_bp.route("/account/stripe/webhook", methods=["POST"])
@csrf.exempt  # CSRF exempt: called by Stripe servers, not browsers. Stripe-Signature header verified instead.
def stripe_webhook():
    import stripe as stripe_lib
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = SiteSettings.get("stripe_webhook_secret", "")
    try:
        event_obj = stripe_lib.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        current_app.logger.warning(f"Stripe webhook signature verification failed: {e}")
        return ("", 400)

    if event_obj["type"] == "checkout.session.completed":
        session_data = event_obj["data"]["object"]
        if session_data.get("payment_status") == "paid":
            reg_id = session_data.get("metadata", {}).get("registration_id")
            registration = db.session.get(Registration, int(reg_id)) if reg_id else None
            if registration and registration.payment_status != "paid":
                registration.payment_status = "paid"
                registration.payment_method = "stripe"
                registration.paid_at = utcnow()
                db.session.commit()

    return ("", 200)


@account_bp.route("/account/paypal/webhook", methods=["POST"])
@csrf.exempt  # CSRF exempt: called by PayPal servers, not browsers. PayPal webhook signature verified instead.
def paypal_webhook():
    import json as _json
    raw_body = request.get_data()
    if not verify_paypal_webhook(request.headers, raw_body):
        return ("", 400)

    try:
        data = _json.loads(raw_body)
    except Exception as e:
        current_app.logger.warning(f"PayPal webhook body was not valid JSON: {e}")
        return ("", 400)

    if data.get("event_type") == "CHECKOUT.ORDER.APPROVED":
        resource = data.get("resource", {})
        order_id = resource.get("id")
        registration = Registration.query.filter_by(paypal_order_id=order_id).first()
        if registration and registration.payment_status != "paid":
            if capture_paypal_order(order_id):
                registration.payment_status = "paid"
                registration.payment_method = "paypal"
                registration.paid_at = utcnow()
                db.session.commit()

    return ("", 200)


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


def _render_seat_grid(event, reg):
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
        "account/seats_grid_partial.html",
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
    if request.headers.get("HX-Request"):
        return _render_seat_grid(event, reg)
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
    if request.headers.get("HX-Request"):
        return _render_seat_grid(event, reg)
    flash("Seat released.", "success")
    return redirect(url_for("account.my_registration", slug=slug))


def _sync_needs_loaner(reg):
    """Set reg.needs_loaner=True if an active (non-denied) LoanerRequest exists."""
    active = reg.loaner_requests.filter(LoanerRequest.status != "denied").first()
    reg.needs_loaner = active is not None


@account_bp.route("/events/<slug>/my-registration/loaner", methods=["POST"])
@login_required
def update_loaner(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)
    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    if reg.status == "cancelled" or not event.is_upcoming:
        abort(403)

    equipment_id_raw = request.form.get("equipment_id", "none").strip()

    # Cancel any existing active loaner request first
    existing = reg.loaner_requests.filter(LoanerRequest.status != "denied").first()
    if existing:
        db.session.delete(existing)

    if equipment_id_raw != "none":
        equipment_id = None
        if equipment_id_raw != "0":
            try:
                equipment_id = int(equipment_id_raw)
                eq = db.session.get(LoanerEquipment, equipment_id)
                if eq is None:
                    flash("Equipment not found.", "error")
                    return redirect(url_for("account.my_registration", slug=slug))
            except ValueError:
                equipment_id = None

        loaner_req = LoanerRequest(
            registration_id=reg.id,
            equipment_id=equipment_id,
            status="requested",
        )
        db.session.add(loaner_req)
        reg.needs_loaner = True
        flash("Loaner request saved.", "success")
    else:
        reg.needs_loaner = False
        flash("Loaner request removed.", "success")

    db.session.commit()
    return redirect(url_for("account.my_registration", slug=slug))


@account_bp.route("/events/<slug>/my-registration/potluck/add", methods=["POST"])
@login_required
def potluck_add(slug):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)
    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    if reg.status == "cancelled" or not event.is_upcoming:
        abort(403)

    form = PotluckItemForm()
    if form.validate_on_submit():
        item = PotluckItem(
            event_id=event.id,
            registration_id=reg.id,
            description=form.description.data,
        )
        db.session.add(item)
        db.session.commit()
        flash("Item added to potluck list.", "success")
    else:
        flash("Please enter a description.", "error")
    return redirect(url_for("account.my_registration", slug=slug))


@account_bp.route("/events/<slug>/my-registration/potluck/<int:item_id>/delete", methods=["POST"])
@login_required
def potluck_delete(slug, item_id):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)
    reg = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first_or_404()

    item = db.session.get(PotluckItem, item_id)
    if item is None or item.registration_id != reg.id:
        abort(403)

    db.session.delete(item)
    db.session.commit()
    flash("Item removed from potluck list.", "success")
    return redirect(url_for("account.my_registration", slug=slug))


# ---------------------------------------------------------------------------
# Tournament self-registration
# ---------------------------------------------------------------------------


def _challonge_configured_account():
    return bool(
        SiteSettings.get("challonge_api_key", "")
        and SiteSettings.get("challonge_username", "")
    )


@account_bp.route("/events/<slug>/tournaments/<int:tid>/signup", methods=["POST"])
@login_required
def tournament_signup(slug, tid):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    registration = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()
    if registration is None or registration.status == "cancelled":
        flash("You must have a confirmed registration for this event to join a tournament.", "warning")
        return redirect(url_for("public.event_detail", slug=slug))

    tournament = db.session.get(Tournament, tid)
    if tournament is None or tournament.event_id != event.id:
        abort(404)

    if not tournament.sign_ups_open:
        flash("Sign-ups for this tournament are closed.", "warning")
        return redirect(url_for("account.my_registration", slug=slug))

    if tournament.status != "pending":
        flash("This tournament is no longer accepting sign-ups.", "warning")
        return redirect(url_for("account.my_registration", slug=slug))

    already = TournamentParticipant.query.filter_by(
        tournament_id=tid, registration_id=registration.id
    ).first()
    if already:
        flash("You are already signed up for this tournament.", "info")
        return redirect(url_for("account.my_registration", slug=slug))

    cp_id = None
    if tournament.challonge_url_slug and _challonge_configured_account():
        try:
            result = challonge.add_participants_bulk(
                tournament.challonge_url_slug, [{"name": current_user.public_name}]
            )
            if isinstance(result, list) and result:
                cp_id = result[0]["participant"]["id"]
        except http_requests.RequestException as e:
            current_app.logger.warning(f"Challonge signup failed for tournament {tid}: {e}")

    participant = TournamentParticipant(
        tournament_id=tid,
        registration_id=registration.id,
        challonge_participant_id=cp_id,
        display_name=current_user.public_name,
    )
    db.session.add(participant)
    db.session.commit()
    flash("You've signed up for the tournament!", "success")
    return redirect(url_for("account.my_registration", slug=slug))


@account_bp.route("/events/<slug>/tournaments/<int:tid>/withdraw", methods=["POST"])
@login_required
def tournament_withdraw(slug, tid):
    event = db.session.execute(
        select(Event).filter_by(slug=slug, status="published")
    ).scalar_one_or_none()
    if event is None:
        abort(404)

    registration = Registration.query.filter_by(
        user_id=current_user.id, event_id=event.id
    ).first()
    if registration is None:
        abort(404)

    tournament = db.session.get(Tournament, tid)
    if tournament is None or tournament.event_id != event.id:
        abort(404)

    if tournament.status in ("underway", "complete"):
        flash("Cannot withdraw from a tournament that is already underway.", "warning")
        return redirect(url_for("account.my_registration", slug=slug))

    participant = TournamentParticipant.query.filter_by(
        tournament_id=tid, registration_id=registration.id
    ).first()
    if participant is None:
        flash("You are not signed up for this tournament.", "info")
        return redirect(url_for("account.my_registration", slug=slug))

    if participant.challonge_participant_id and tournament.challonge_url_slug:
        try:
            challonge.remove_participant(tournament.challonge_url_slug, participant.challonge_participant_id)
        except http_requests.RequestException as e:
            current_app.logger.warning(f"Challonge withdraw failed for tournament {tid}: {e}")

    db.session.delete(participant)
    db.session.commit()
    flash("You've withdrawn from the tournament.", "success")
    return redirect(url_for("account.my_registration", slug=slug))


# ---------------------------------------------------------------------------
# 2FA / TOTP security routes
# ---------------------------------------------------------------------------

@account_bp.route("/account/security")
@login_required
def security():
    backup_code_count = 0
    if current_user.totp_backup_codes:
        try:
            backup_code_count = len(json.loads(current_user.totp_backup_codes))
        except Exception as e:
            current_app.logger.warning(f"Failed to parse totp_backup_codes for user {current_user.id}: {e}")
            backup_code_count = 0
    return render_template(
        "account/security.html",
        backup_code_count=backup_code_count,
    )


@account_bp.route("/account/security/setup")
@login_required
def security_setup():
    if current_user.has_2fa:
        return redirect(url_for("account.security"))
    secret = session.get("totp_setup_secret") or generate_totp_secret()
    session["totp_setup_secret"] = secret
    uri = get_totp_uri(secret, current_user.email)
    qr_data_uri = qr_code_data_uri(uri)
    return render_template(
        "account/security_setup.html",
        qr_data_uri=qr_data_uri,
        secret=secret,
    )


@account_bp.route("/account/security/verify-setup", methods=["POST"])
@login_required
def security_verify_setup():
    secret = session.get("totp_setup_secret")
    if not secret:
        return redirect(url_for("account.security_setup"))
    code = request.form.get("code", "").strip()
    if not verify_totp_code(secret, code):
        flash("Invalid code. Please try the code from your app.", "error")
        uri = get_totp_uri(secret, current_user.email)
        qr_data_uri = qr_code_data_uri(uri)
        return render_template("account/security_setup.html",
                               qr_data_uri=qr_data_uri, secret=secret)
    raw_codes, hashed_codes = generate_backup_codes()
    current_user.totp_secret = secret
    current_user.totp_backup_codes = json.dumps(hashed_codes)
    db.session.commit()
    session.pop("totp_setup_secret", None)
    session["totp_backup_codes_display"] = raw_codes
    flash("Two-factor authentication enabled!", "success")
    return redirect(url_for("account.security_backup_codes_display"))


@account_bp.route("/account/security/backup-codes-display")
@login_required
def security_backup_codes_display():
    raw_codes = session.pop("totp_backup_codes_display", None)
    if raw_codes is None:
        return redirect(url_for("account.security"))
    return render_template("account/backup_codes_display.html", codes=raw_codes)


@account_bp.route("/account/security/disable", methods=["POST"])
@login_required
def security_disable():
    password = request.form.get("password", "")
    if not current_user.check_password(password):
        flash("Incorrect password.", "error")
        return redirect(url_for("account.security"))
    current_user.totp_secret = None
    current_user.totp_backup_codes = None
    db.session.commit()
    flash("Two-factor authentication disabled.", "success")
    return redirect(url_for("account.security"))


@account_bp.route("/account/security/regenerate-backup-codes", methods=["POST"])
@login_required
def security_regenerate_backup_codes():
    if not current_user.has_2fa:
        flash("Two-factor authentication is not enabled.", "error")
        return redirect(url_for("account.security"))
    password = request.form.get("password", "")
    if not current_user.check_password(password):
        flash("Incorrect password.", "error")
        return redirect(url_for("account.security"))
    raw_codes, hashed_codes = generate_backup_codes()
    current_user.totp_backup_codes = json.dumps(hashed_codes)
    db.session.commit()
    session["totp_backup_codes_display"] = raw_codes
    flash("New backup codes generated. Save them now.", "success")
    return redirect(url_for("account.security_backup_codes_display"))
