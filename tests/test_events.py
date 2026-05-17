import json
from datetime import timedelta
from uuid import uuid4

from models import EventQuestion, Registration, RegistrationAnswer, TicketType, db, utcnow


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
    client.post("/logout")

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


# ---------------------------------------------------------------------------
# Custom Question Builder — registration
# ---------------------------------------------------------------------------

def _make_question(published_event, question_type="text", is_required=False, options=None):
    q = EventQuestion(
        event_id=published_event.id,
        question_text="Test Question",
        question_type=question_type,
        field_name="test_question",
        is_required=is_required,
        display_order=0,
        options=json.dumps(options) if options else None,
    )
    db.session.add(q)
    db.session.commit()
    return q


def test_required_question_rejects_registration_without_answer(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    _make_question(published_event, question_type="text", is_required=True)

    r = client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"is required" in r.data
    assert Registration.query.count() == 0


def test_optional_question_allows_registration_without_answer(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    _make_question(published_event, question_type="text", is_required=False)

    r = client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert Registration.query.count() == 1


def test_answers_saved_on_registration(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    q = _make_question(published_event, question_type="text", is_required=False)

    client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id, "test_question": "My Answer"},
        follow_redirects=True,
    )
    ans = RegistrationAnswer.query.filter_by(question_id=q.id).first()
    assert ans is not None
    assert ans.answer == "My Answer"


def test_boolean_answer_stored_as_true_string(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    q = _make_question(published_event, question_type="boolean")

    client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id, "test_question": "on"},
        follow_redirects=True,
    )
    ans = RegistrationAnswer.query.filter_by(question_id=q.id).first()
    assert ans is not None
    assert ans.answer == "true"


def test_boolean_unchecked_stored_as_false_string(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    q = _make_question(published_event, question_type="boolean")

    client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id},
        follow_redirects=True,
    )
    # unchecked boolean is stored as "false" string
    ans = RegistrationAnswer.query.filter_by(question_id=q.id).first()
    assert ans is not None
    assert ans.answer == "false"


def test_select_answer_stored_as_option_text(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    q = _make_question(published_event, question_type="select", options=["Small", "Medium", "Large"])

    client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id, "test_question": "Medium"},
        follow_redirects=True,
    )
    ans = RegistrationAnswer.query.filter_by(question_id=q.id).first()
    assert ans is not None
    assert ans.answer == "Medium"


def test_answers_shown_on_my_registration(client, regular_user, published_event, ticket_type):
    _login(client, regular_user)
    q = _make_question(published_event, question_type="text")

    client.post(
        "/events/test-lan-party/register",
        data={"ticket_type_id": ticket_type.id, "test_question": "BoardGameGeek"},
        follow_redirects=True,
    )
    r = client.get("/events/test-lan-party/my-registration")
    assert r.status_code == 200
    assert b"Test Question" in r.data
    assert b"BoardGameGeek" in r.data


def test_answers_updateable_via_post(client, regular_user, published_event, ticket_type, registration):
    q = _make_question(published_event, question_type="text")
    ans = RegistrationAnswer(registration_id=registration.id, question_id=q.id, answer="Old")
    db.session.add(ans)
    db.session.commit()
    ans_id = ans.id

    _login(client, regular_user)
    r = client.post(
        "/events/test-lan-party/my-registration/answers",
        data={"test_question": "New"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    db.session.expire_all()
    updated = db.session.get(RegistrationAnswer, ans_id)
    assert updated.answer == "New"


def test_unique_constraint_prevents_duplicate_answers(app, regular_user, published_event, ticket_type):
    with app.app_context():
        q = EventQuestion(
            event_id=published_event.id,
            question_text="Unique Test",
            question_type="text",
            field_name="unique_test",
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

        db.session.add(RegistrationAnswer(registration_id=reg.id, question_id=q.id, answer="First"))
        db.session.commit()

        import sqlalchemy.exc
        db.session.add(RegistrationAnswer(registration_id=reg.id, question_id=q.id, answer="Second"))
        try:
            db.session.commit()
            assert False, "Should have raised IntegrityError"
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
