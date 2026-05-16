import csv
import io
import json
from uuid import uuid4

from models import Event, EventQuestion, Registration, RegistrationAnswer, Seat, SiteSettings, TicketType, User, db
from models import utcnow


ADMIN_ROUTES = [
    "/admin/",
    "/admin/settings",
    "/admin/events",
    "/admin/events/new",
    "/admin/logs",
]


def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_admin_routes_redirect_unauthenticated(client):
    for route in ADMIN_ROUTES:
        response = client.get(route)
        assert response.status_code == 302, f"{route} should redirect unauthenticated users"
        assert "/login" in response.headers["Location"], f"{route} should redirect to login"


def test_admin_routes_return_403_for_non_admin(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    for route in ADMIN_ROUTES:
        response = client.get(route)
        assert response.status_code == 403, f"{route} should return 403 for non-admin users"


def test_admin_routes_return_200_for_admin(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    for route in ADMIN_ROUTES:
        response = client.get(route)
        assert response.status_code == 200, f"{route} should return 200 for admin users"


def test_settings_saves_and_reads_back(client, admin_user):
    db.session.add(SiteSettings(key="ui_theme", value="dark"))
    db.session.add(SiteSettings(key="site_name", value="Ludus"))
    db.session.add(SiteSettings(key="site_tagline", value=""))
    db.session.add(SiteSettings(key="contact_email", value=""))
    db.session.add(SiteSettings(key="logo_url", value=""))
    db.session.add(SiteSettings(key="favicon_url", value=""))
    db.session.add(SiteSettings(key="venmo_handle", value=""))
    db.session.add(SiteSettings(key="discord_url", value=""))
    db.session.add(SiteSettings(key="twitch_url", value=""))
    db.session.add(SiteSettings(key="youtube_url", value=""))
    db.session.add(SiteSettings(key="instagram_url", value=""))
    db.session.add(SiteSettings(key="facebook_url", value=""))
    db.session.add(SiteSettings(key="terms_of_service", value=""))
    db.session.add(SiteSettings(key="privacy_policy", value=""))
    db.session.add(SiteSettings(key="registration_enabled", value="true"))
    db.session.add(SiteSettings(key="show_upcoming_event_on_homepage", value="true"))
    db.session.commit()

    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        "/admin/settings",
        data={
            "site_name": "My Event Site",
            "site_tagline": "Have fun",
            "contact_email": "",
            "logo_url": "",
            "favicon_url": "",
            "venmo_handle": "",
            "discord_url": "",
            "twitch_url": "",
            "youtube_url": "",
            "instagram_url": "",
            "facebook_url": "",
            "terms_of_service": "",
            "privacy_policy": "",
            "registration_enabled": "y",
            "ui_theme": "dracula",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    assert SiteSettings.get("ui_theme") == "dracula"
    assert SiteSettings.get("site_name") == "My Event Site"


def test_seed_settings_is_idempotent(app):
    with app.app_context():
        runner = app.test_cli_runner()

        result = runner.invoke(args=["seed-settings"])
        assert "Seeded" in result.output
        assert "setting(s)" in result.output

        result = runner.invoke(args=["seed-settings"])
        assert "0" in result.output


def test_create_admin_promotes_user(app, regular_user):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-admin", "user@example.com"])
    assert "now an admin" in result.output

    from models import User
    user = User.query.filter_by(email="user@example.com").first()
    assert user.is_admin is True


def test_create_admin_unknown_email(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-admin", "nobody@example.com"])
    assert "No user found" in result.output


# ---------------------------------------------------------------------------
# Phase 4: Event management
# ---------------------------------------------------------------------------

_EVENT_DATA = {
    "name": "Summer LAN 2026",
    "slug": "",
    "type": "lan",
    "status": "draft",
    "short_description": "Annual summer LAN.",
    "description": "<p>Description</p>",
    "start_datetime": "2026-08-07T18:00",
    "end_datetime": "2026-08-09T18:00",
    "location": "Community Center",
    "cover_image_url": "",
    "gallery_url": "",
    "registration_open": "y",
    "registration_closes_at": "",
}


def test_admin_events_list_returns_200(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get("/admin/events")
    assert response.status_code == 200
    assert b"Events" in response.data


def test_admin_events_list_shows_all_statuses(client, admin_user, published_event, draft_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get("/admin/events")
    assert b"Test LAN Party" in response.data
    assert b"Secret Draft Event" in response.data


def test_admin_event_create_get_returns_200(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get("/admin/events/new")
    assert response.status_code == 200


def test_admin_event_create_post_creates_event(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post("/admin/events/new", data=_EVENT_DATA, follow_redirects=False)
    assert response.status_code == 302
    event = Event.query.filter_by(name="Summer LAN 2026").first()
    assert event is not None


def test_admin_event_create_autogenerates_slug(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    data = {**_EVENT_DATA, "name": "My Cool Event", "slug": ""}
    client.post("/admin/events/new", data=data)
    event = Event.query.filter_by(name="My Cool Event").first()
    assert event is not None
    assert event.slug == "my-cool-event"


def test_admin_event_slug_uniqueness(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    # published_event has slug "test-lan-party"; create another with the same name
    data = {**_EVENT_DATA, "name": "Test LAN Party", "slug": ""}
    client.post("/admin/events/new", data=data)
    second = Event.query.filter(Event.id != published_event.id).first()
    assert second is not None
    assert second.slug == "test-lan-party-2"


def test_admin_event_detail_returns_200(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}")
    assert response.status_code == 200
    assert b"Test LAN Party" in response.data


def test_admin_event_edit_get_returns_200(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/edit")
    assert response.status_code == 200


def test_admin_event_edit_post_updates_event(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    data = {
        **_EVENT_DATA,
        "name": "Updated Name",
        "slug": "test-lan-party",
        "status": "published",
    }
    response = client.post(
        f"/admin/events/{published_event.id}/edit", data=data, follow_redirects=False
    )
    assert response.status_code == 302
    db.session.refresh(published_event)
    assert published_event.name == "Updated Name"


def test_admin_event_clone_creates_copy(client, admin_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/clone", follow_redirects=False
    )
    assert response.status_code == 302
    assert Event.query.count() == 2
    clone = Event.query.filter(Event.name.like("Copy of%")).first()
    assert clone is not None
    assert clone.status == "draft"
    assert TicketType.query.filter_by(event_id=clone.id).count() == 1


def test_admin_event_toggle_status_published(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/toggle-status",
        data={"status": "archived"},
    )
    assert response.status_code == 200
    db.session.refresh(published_event)
    assert published_event.status == "archived"


def test_admin_event_toggle_status_invalid_returns_400(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/toggle-status",
        data={"status": "bogus"},
    )
    assert response.status_code == 400


def test_admin_tickets_list_returns_200(client, admin_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/tickets")
    assert response.status_code == 200
    assert b"Weekend Pass" in response.data


def test_admin_ticket_create_get_returns_200(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/tickets/new")
    assert response.status_code == 200


def test_admin_ticket_create_post_creates_ticket(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    data = {
        "name": "Day Pass",
        "description": "",
        "price": "0",
        "quantity_total": "10",
        "max_per_user": "1",
        "is_active": "y",
        "valid_days": "2026-08-07",
    }
    response = client.post(
        f"/admin/events/{published_event.id}/tickets/new", data=data, follow_redirects=False
    )
    assert response.status_code == 302
    assert TicketType.query.filter_by(name="Day Pass").first() is not None


def test_admin_ticket_create_requires_valid_days(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    data = {
        "name": "No Days Pass",
        "price": "0",
        "quantity_total": "5",
        "max_per_user": "1",
        # no valid_days
    }
    response = client.post(
        f"/admin/events/{published_event.id}/tickets/new", data=data
    )
    assert response.status_code == 200  # re-renders form
    assert TicketType.query.count() == 0


def test_admin_ticket_edit_get_returns_200(client, admin_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/tickets/{ticket_type.id}/edit")
    assert response.status_code == 200


def test_admin_ticket_edit_post_updates_ticket(client, admin_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    data = {
        "name": "VIP Pass",
        "description": "",
        "price": "50",
        "quantity_total": "5",
        "max_per_user": "1",
        "is_active": "y",
        "valid_days": "2026-08-07",
    }
    response = client.post(
        f"/admin/events/{published_event.id}/tickets/{ticket_type.id}/edit",
        data=data,
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(ticket_type)
    assert ticket_type.name == "VIP Pass"


def test_admin_ticket_edit_wrong_event_returns_404(client, admin_user, published_event, draft_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    # ticket_type belongs to published_event; try to access via draft_event's id
    response = client.get(f"/admin/events/{draft_event.id}/tickets/{ticket_type.id}/edit")
    assert response.status_code == 404


def test_admin_event_capacity_computed_from_tickets(app, published_event, ticket_type):
    assert published_event.capacity == 30
    second = TicketType(
        event_id=published_event.id,
        name="Day Pass",
        price=0,
        quantity_total=10,
        seatable=False,
        includes_lodging=False,
        valid_days=json.dumps(["2026-08-07"]),
        max_per_user=1,
        is_active=True,
    )
    db.session.add(second)
    db.session.commit()
    db.session.refresh(published_event)
    assert published_event.capacity == 40


# ---------------------------------------------------------------------------
# Phase 4: Dynamic admin route security sweep
# ---------------------------------------------------------------------------

def _dynamic_admin_routes(published_event, ticket_type):
    return [
        f"/admin/events/{published_event.id}",
        f"/admin/events/{published_event.id}/edit",
        f"/admin/events/{published_event.id}/tickets",
        f"/admin/events/{published_event.id}/tickets/new",
        f"/admin/events/{published_event.id}/tickets/{ticket_type.id}/edit",
    ]


def test_dynamic_admin_routes_redirect_unauthenticated(client, published_event, ticket_type):
    for route in _dynamic_admin_routes(published_event, ticket_type):
        response = client.get(route)
        assert response.status_code == 302, f"{route} should redirect unauthenticated"
        assert "/login" in response.headers["Location"], f"{route} should redirect to login"


def test_dynamic_admin_routes_return_403_for_non_admin(client, regular_user, published_event, ticket_type):
    _login(client, "user@example.com", "userpass123")
    for route in _dynamic_admin_routes(published_event, ticket_type):
        response = client.get(route)
        assert response.status_code == 403, f"{route} should return 403 for non-admin"


def test_dynamic_admin_routes_return_200_for_admin(client, admin_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    for route in _dynamic_admin_routes(published_event, ticket_type):
        response = client.get(route)
        assert response.status_code == 200, f"{route} should return 200 for admin"


# ---------------------------------------------------------------------------
# Phase 4: Cascade delete
# ---------------------------------------------------------------------------

def test_event_delete_cascades_to_ticket_types(app, published_event, ticket_type):
    event_id = published_event.id
    assert TicketType.query.filter_by(event_id=event_id).count() == 1
    db.session.delete(published_event)
    db.session.commit()
    assert TicketType.query.filter_by(event_id=event_id).count() == 0


# ---------------------------------------------------------------------------
# Phase 6: Admin registration management
# ---------------------------------------------------------------------------


def test_registrations_list_returns_200_for_admin(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/registrations")
    assert response.status_code == 200
    assert b"Regular" in response.data


def test_registrations_list_returns_403_for_non_admin(client, regular_user, published_event, ticket_type, registration):
    _login(client, "user@example.com", "userpass123")
    response = client.get(f"/admin/events/{published_event.id}/registrations")
    assert response.status_code == 403


def test_registrations_list_htmx_returns_partial(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(
        f"/admin/events/{published_event.id}/registrations",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert b"<html" not in response.data


def test_registration_detail_returns_200(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/registrations/{registration.id}")
    assert response.status_code == 200
    assert b"Regular" in response.data


def test_mark_paid_updates_payment_status(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/mark-paid",
        data={"paid-payment_method": "venmo", "paid-submit": "Mark Paid"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.payment_status == "paid"
    assert registration.payment_method == "venmo"
    assert registration.paid_at is not None


def test_mark_paid_confirms_pending_registration(client, admin_user, published_event, ticket_type, registration):
    registration.status = "pending"
    db.session.commit()
    _login(client, "admin@example.com", "adminpass123")
    client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/mark-paid",
        data={"paid-payment_method": "cash", "paid-submit": "Mark Paid"},
    )
    db.session.refresh(registration)
    assert registration.status == "confirmed"


def test_mark_comped_sets_payment_status(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/mark-comped",
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.payment_status == "comped"


def test_checkin_sets_checked_in_at(client, admin_user, published_event, ticket_type, registration):
    assert registration.checked_in_at is None
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/check-in",
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.checked_in_at is not None


def test_undo_checkin_clears_checked_in_at(client, admin_user, published_event, ticket_type, registration):
    from datetime import datetime
    registration.checked_in_at = datetime(2026, 8, 7, 20, 0, 0)
    db.session.commit()

    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/undo-checkin",
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.checked_in_at is None


def test_cancel_sets_status_cancelled(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/cancel",
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.status == "cancelled"
    assert registration.seat_id is None


def test_admin_notes_saves(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/notes",
        data={"notes-admin_notes": "Bring a power strip.", "notes-submit": "Save Notes"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.admin_notes == "Bring a power strip."


def test_csv_export_returns_csv(client, admin_user, published_event, ticket_type, registration):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/events/{published_event.id}/registrations/export.csv")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Name,Email" in response.data
    assert b"Regular" in response.data


# ---------------------------------------------------------------------------
# Phase 7: Seat management
# ---------------------------------------------------------------------------

def test_seat_add_creates_seat(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/seats/add",
        data={"single-label": "Table A", "single-display_order": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert Seat.query.filter_by(event_id=published_event.id, label="Table A").first() is not None


def test_seat_bulk_add_creates_correct_count(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    client.post(
        f"/admin/events/{published_event.id}/seats/bulk-add",
        data={"bulk-prefix": "Seat", "bulk-count": "5", "bulk-start_number": "1"},
        follow_redirects=False,
    )
    seats = Seat.query.filter_by(event_id=published_event.id).all()
    assert len(seats) == 5
    assert {s.label for s in seats} == {"Seat 1", "Seat 2", "Seat 3", "Seat 4", "Seat 5"}


def test_seat_delete_blocked_when_claimed(client, admin_user, published_event, ticket_type, registration, seat):
    registration.seat_id = seat.id
    db.session.commit()
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/seats/{seat.id}/delete",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Cannot delete" in response.data
    assert db.session.get(Seat, seat.id) is not None


def test_seat_delete_succeeds_when_unclaimed(client, admin_user, published_event, seat):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/seats/{seat.id}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert db.session.get(Seat, seat.id) is None


def test_registration_assign_seat(client, admin_user, published_event, ticket_type, registration, seat):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/assign-seat",
        data={"seat_id": str(seat.id)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(registration)
    assert registration.seat_id == seat.id


def test_registration_assign_seat_blocked_if_taken(
    client, admin_user, published_event, ticket_type, registration, seat
):
    other = User(name="Other", email="other@example.com", email_verified_at=utcnow())
    other.set_password("otherpass123")
    db.session.add(other)
    db.session.commit()
    other_reg = Registration(
        user_id=other.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
        seat_id=seat.id,
    )
    db.session.add(other_reg)
    db.session.commit()

    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/events/{published_event.id}/registrations/{registration.id}/assign-seat",
        data={"seat_id": str(seat.id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"already claimed" in response.data
    db.session.refresh(registration)
    assert registration.seat_id is None


# ---------------------------------------------------------------------------
# Phase 8: User management admin
# ---------------------------------------------------------------------------

def test_users_list_returns_200_for_admin(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get("/admin/users")
    assert response.status_code == 200


def test_user_detail_returns_200_for_admin(client, admin_user, regular_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get(f"/admin/users/{regular_user.id}")
    assert response.status_code == 200
    assert b"Regular" in response.data


def test_user_toggle_admin_grants_admin(client, admin_user, regular_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/users/{regular_user.id}/toggle-admin",
        follow_redirects=False,
    )
    assert response.status_code == 302
    db.session.refresh(regular_user)
    assert regular_user.is_admin is True


def test_user_toggle_admin_cannot_remove_own_status(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        f"/admin/users/{admin_user.id}/toggle-admin",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"cannot change your own" in response.data
    db.session.refresh(admin_user)
    assert admin_user.is_admin is True


def test_user_toggle_admin_cannot_remove_last_admin(client, admin_user):
    second = User(
        name="Second Admin", email="second@example.com",
        is_admin=True, email_verified_at=utcnow(),
    )
    second.set_password("secondpass123")
    db.session.add(second)
    db.session.commit()

    # Log in as second admin and revoke the first — now second is the only admin
    _login(client, "second@example.com", "secondpass123")
    client.post(f"/admin/users/{admin_user.id}/toggle-admin", follow_redirects=False)
    db.session.refresh(admin_user)
    assert admin_user.is_admin is False

    # Attempt to revoke the sole remaining admin (self) — blocked by self-check;
    # the last-admin guard is the defence-in-depth for concurrent requests.
    # Either way, second.is_admin must stay True.
    response = client.post(
        f"/admin/users/{second.id}/toggle-admin",
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.refresh(second)
    assert second.is_admin is True  # invariant: always at least one admin


# ---------------------------------------------------------------------------
# Phase 9: Mass email
# ---------------------------------------------------------------------------

def test_email_compose_get_returns_200(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.get("/admin/email")
    assert response.status_code == 200


def test_email_compose_post_sends_and_flashes_count(client, admin_user, regular_user):
    _login(client, "admin@example.com", "adminpass123")
    response = client.post(
        "/admin/email",
        data={
            "event_id": "0",
            "recipient_filter": "all",
            "subject": "Test email",
            "body": "<p>Hello!</p>",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Sent to" in response.data


# ---------------------------------------------------------------------------
# Security sweep: phases 7–10 new routes
# ---------------------------------------------------------------------------

def _phase_7_10_admin_routes(published_event, admin_user):
    return [
        f"/admin/events/{published_event.id}/seats",
        "/admin/users",
        f"/admin/users/{admin_user.id}",
        "/admin/email",
    ]


def test_phase_7_10_routes_redirect_unauthenticated(client, published_event, admin_user):
    for route in _phase_7_10_admin_routes(published_event, admin_user):
        r = client.get(route)
        assert r.status_code == 302, f"{route}: expected 302"
        assert "/login" in r.headers["Location"], f"{route}: expected login redirect"


def test_phase_7_10_routes_return_403_for_non_admin(client, regular_user, published_event, admin_user):
    _login(client, "user@example.com", "userpass123")
    for route in _phase_7_10_admin_routes(published_event, admin_user):
        r = client.get(route)
        assert r.status_code == 403, f"{route}: expected 403"


def test_phase_7_10_routes_return_200_for_admin(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    for route in _phase_7_10_admin_routes(published_event, admin_user):
        r = client.get(route)
        assert r.status_code == 200, f"{route}: expected 200"


# ---------------------------------------------------------------------------
# Custom Question Builder
# ---------------------------------------------------------------------------

def test_questions_list_returns_200(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    r = client.get(f"/admin/events/{published_event.id}/questions")
    assert r.status_code == 200


def test_questions_list_unauthenticated_redirects(client, published_event):
    r = client.get(f"/admin/events/{published_event.id}/questions")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_questions_list_non_admin_returns_403(client, regular_user, published_event):
    _login(client, "user@example.com", "userpass123")
    r = client.get(f"/admin/events/{published_event.id}/questions")
    assert r.status_code == 403


def test_add_question_creates_record_with_field_name_slug(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    r = client.post(
        f"/admin/events/{published_event.id}/questions/add",
        data={
            "question_text": "Dietary Restrictions",
            "question_type": "text",
            "display_order": "0",
            "options": "",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    q = EventQuestion.query.filter_by(event_id=published_event.id).first()
    assert q is not None
    assert q.field_name == "dietary_restrictions"
    assert q.question_type == "text"
    assert q.is_required is False


def test_add_required_question(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    client.post(
        f"/admin/events/{published_event.id}/questions/add",
        data={
            "question_text": "T-Shirt Size",
            "question_type": "text",
            "is_required": "y",
            "display_order": "0",
        },
        follow_redirects=True,
    )
    q = EventQuestion.query.filter_by(question_text="T-Shirt Size").first()
    assert q is not None
    assert q.is_required is True


def test_add_select_question_stores_options_as_json(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    client.post(
        f"/admin/events/{published_event.id}/questions/add",
        data={
            "question_text": "Shirt Size",
            "question_type": "select",
            "options": "Small\nMedium\nLarge",
            "display_order": "0",
        },
        follow_redirects=True,
    )
    q = EventQuestion.query.filter_by(question_text="Shirt Size").first()
    assert q is not None
    assert json.loads(q.options) == ["Small", "Medium", "Large"]


def test_add_boolean_question(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    client.post(
        f"/admin/events/{published_event.id}/questions/add",
        data={
            "question_text": "Do you need parking?",
            "question_type": "boolean",
            "display_order": "0",
        },
        follow_redirects=True,
    )
    q = EventQuestion.query.filter_by(question_text="Do you need parking?").first()
    assert q is not None
    assert q.question_type == "boolean"
    assert q.options is None


def test_edit_question_updates_fields(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    q = EventQuestion(
        event_id=published_event.id,
        question_text="Old Text",
        question_type="text",
        field_name="old_text",
        is_required=False,
        display_order=0,
    )
    db.session.add(q)
    db.session.commit()
    qid = q.id

    client.post(
        f"/admin/events/{published_event.id}/questions/{qid}/edit",
        data={
            "question_text": "New Text",
            "question_type": "text",
            "is_required": "y",
            "display_order": "5",
            "options": "",
        },
        follow_redirects=True,
    )
    db.session.expire_all()
    updated = db.session.get(EventQuestion, qid)
    assert updated.question_text == "New Text"
    assert updated.is_required is True
    assert updated.display_order == 5


def test_delete_question_without_answers_succeeds(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    q = EventQuestion(
        event_id=published_event.id,
        question_text="Delete Me",
        question_type="text",
        field_name="delete_me",
        is_required=False,
        display_order=0,
    )
    db.session.add(q)
    db.session.commit()
    qid = q.id

    r = client.post(
        f"/admin/events/{published_event.id}/questions/{qid}/delete",
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert db.session.get(EventQuestion, qid) is None


def test_delete_question_with_answers_is_blocked(client, admin_user, regular_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")
    q = EventQuestion(
        event_id=published_event.id,
        question_text="Has Answers",
        question_type="text",
        field_name="has_answers",
        is_required=False,
        display_order=0,
    )
    db.session.add(q)
    db.session.flush()

    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    db.session.add(reg)
    db.session.flush()

    ans = RegistrationAnswer(registration_id=reg.id, question_id=q.id, answer="some answer")
    db.session.add(ans)
    db.session.commit()
    qid = q.id

    r = client.post(
        f"/admin/events/{published_event.id}/questions/{qid}/delete",
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert db.session.get(EventQuestion, qid) is not None
    assert b"Cannot delete" in r.data


def test_csv_export_includes_question_columns(client, admin_user, regular_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")

    q = EventQuestion(
        event_id=published_event.id,
        question_text="Favourite Snack",
        question_type="text",
        field_name="favourite_snack",
        is_required=False,
        display_order=0,
    )
    db.session.add(q)
    db.session.flush()

    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    db.session.add(reg)
    db.session.flush()

    ans = RegistrationAnswer(registration_id=reg.id, question_id=q.id, answer="Chips")
    db.session.add(ans)
    db.session.commit()

    r = client.get(f"/admin/events/{published_event.id}/registrations/export.csv")
    assert r.status_code == 200
    content = r.data.decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[0][-1] == "Favourite Snack"
    assert rows[1][-1] == "Chips"


def test_csv_export_empty_answer_is_empty_string(client, admin_user, regular_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")

    q = EventQuestion(
        event_id=published_event.id,
        question_text="Optional Question",
        question_type="text",
        field_name="optional_question",
        is_required=False,
        display_order=0,
    )
    db.session.add(q)
    db.session.flush()

    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    db.session.add(reg)
    db.session.commit()

    r = client.get(f"/admin/events/{published_event.id}/registrations/export.csv")
    assert r.status_code == 200
    content = r.data.decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[1][-1] == ""


def test_admin_registration_detail_shows_qa(client, admin_user, regular_user, published_event, ticket_type):
    _login(client, "admin@example.com", "adminpass123")

    q = EventQuestion(
        event_id=published_event.id,
        question_text="Favourite Game",
        question_type="text",
        field_name="favourite_game",
        is_required=False,
        display_order=0,
    )
    db.session.add(q)
    db.session.flush()

    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    db.session.add(reg)
    db.session.flush()

    ans = RegistrationAnswer(registration_id=reg.id, question_id=q.id, answer="Chess")
    db.session.add(ans)
    db.session.commit()

    r = client.get(f"/admin/events/{published_event.id}/registrations/{reg.id}")
    assert r.status_code == 200
    assert b"Favourite Game" in r.data
    assert b"Chess" in r.data
