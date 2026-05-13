import json
from datetime import timedelta
from uuid import uuid4

from models import Registration, TicketType, db, utcnow


def _login(client, user):
    client.post("/login", data={"email": user.email, "password": "userpass123"})


def test_unverified_user_cannot_register(client, unverified_user, published_event, ticket_type):
    client.post("/login", data={"email": unverified_user.email, "password": "unverifiedpass123"})
    response = client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id},
        follow_redirects=True,
    )
    assert b"verify your email" in response.data.lower()
    assert Registration.query.count() == 0


def test_verified_user_can_register(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    response = client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id},
        follow_redirects=True,
    )
    assert response.status_code == 200
    reg = Registration.query.filter_by(user_id=regular_user.id, event_id=published_event.id).first()
    assert reg is not None
    assert reg.status == "confirmed"
    assert reg.checkin_code is not None


def test_duplicate_registration_rejected(client, regular_user, published_event, ticket_type, registration):
    _login(client, regular_user)
    response = client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id},
        follow_redirects=True,
    )
    assert b"already registered" in response.data.lower()
    assert Registration.query.filter_by(event_id=published_event.id).count() == 1


def test_sold_out_ticket_rejected(client, regular_user, published_event, app):
    from models import User

    # Create a ticket with only 1 spot
    limited_ticket = TicketType(
        event_id=published_event.id,
        name="Limited Pass",
        price=0.00,
        quantity_total=1,
        seatable=False,
        includes_lodging=False,
        valid_days=json.dumps(["2026-08-07"]),
        max_per_user=1,
        is_active=True,
    )
    db.session.add(limited_ticket)
    db.session.commit()

    # Register regular_user to fill the sole spot
    _login(client, regular_user)
    client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": limited_ticket.id},
    )
    client.get("/logout")

    # Create a second verified user and try to register
    second_user = User(name="Second", email="second@example.com", email_verified_at=utcnow())
    second_user.set_password("userpass123")
    db.session.add(second_user)
    db.session.commit()

    client.post("/login", data={"email": "second@example.com", "password": "userpass123"})
    response = client.get("/events/test-lan-party/register", follow_redirects=True)
    assert b"sold out" in response.data.lower()
    assert Registration.query.filter_by(user_id=second_user.id).count() == 0


def test_registration_closed_flag_rejected(client, regular_user, published_event, ticket_type):
    published_event.registration_open = False
    db.session.commit()

    _login(client, regular_user)
    response = client.get("/events/test-lan-party/register", follow_redirects=True)
    assert b"closed" in response.data.lower()
    assert Registration.query.count() == 0


def test_registration_closes_at_in_past_rejected(client, regular_user, published_event, ticket_type):
    published_event.registration_closes_at = utcnow() - timedelta(hours=1)
    db.session.commit()

    _login(client, regular_user)
    response = client.get("/events/test-lan-party/register", follow_redirects=True)
    assert b"closed" in response.data.lower()
    assert Registration.query.count() == 0


def test_confirmation_email_triggered_on_registration(client, regular_user, published_event, ticket_type, app):
    with app.extensions["mail"].record_messages() as outbox:
        _login(client, regular_user)
        client.post(
            "/events/test-lan-party/register",
            data={"ticket_type_id": ticket_type.id},
            follow_redirects=True,
        )
        assert len(outbox) == 1
        assert published_event.name in outbox[0].subject


def test_cancel_sets_status_to_cancelled(client, regular_user, published_event, ticket_type, registration):
    _login(client, regular_user)
    response = client.post(
        "/events/test-lan-party/my-registration/cancel",
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.refresh(registration)
    assert registration.status == "cancelled"


def test_my_registration_404_when_not_registered(client, regular_user, published_event):
    _login(client, regular_user)
    response = client.get("/events/test-lan-party/my-registration")
    assert response.status_code == 404


def test_my_registration_shows_details(client, regular_user, published_event, ticket_type, registration):
    _login(client, regular_user)
    response = client.get("/events/test-lan-party/my-registration")
    assert response.status_code == 200
    assert b"Test LAN Party" in response.data
    assert b"Weekend Pass" in response.data
    assert b"Confirmed" in response.data


def test_dashboard_shows_registrations(client, regular_user, published_event, ticket_type, registration):
    _login(client, regular_user)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Test LAN Party" in response.data
    assert b"Weekend Pass" in response.data
