from models import Event, SiteSettings, db as _db


def test_homepage_shows_upcoming_event(client, published_event):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Test LAN Party" in response.data
    assert b"Next Event" in response.data


def test_homepage_fallback_when_no_events(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Next Event" not in response.data
    assert b"View Events" in response.data


def test_homepage_suppressed_by_setting(client, published_event):
    _db.session.add(SiteSettings(key="show_upcoming_event_on_homepage", value="false"))
    _db.session.commit()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Test LAN Party" not in response.data
    assert b"View Events" in response.data


def test_homepage_ignores_past_event(client, past_event):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Past Board Game Night" not in response.data
    assert b"Next Event" not in response.data


def test_events_listing_shows_published(client, published_event):
    response = client.get("/events")
    assert response.status_code == 200
    assert b"Test LAN Party" in response.data


def test_events_listing_shows_past(client, past_event):
    response = client.get("/events")
    assert response.status_code == 200
    assert b"Past Board Game Night" in response.data


def test_events_listing_hides_draft(client, draft_event):
    response = client.get("/events")
    assert response.status_code == 200
    assert b"Secret Draft Event" not in response.data


def test_events_listing_empty_state(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert b"No events scheduled yet" in response.data


def test_event_detail_200_for_published(client, published_event):
    response = client.get("/events/test-lan-party")
    assert response.status_code == 200
    assert b"Test LAN Party" in response.data
    assert b"Full description here." in response.data
    assert b"Test Venue" in response.data


def test_event_detail_404_unknown_slug(client):
    response = client.get("/events/does-not-exist")
    assert response.status_code == 404


def test_event_detail_404_for_draft(client, draft_event):
    response = client.get("/events/secret-draft")
    assert response.status_code == 404


def test_event_detail_shows_lan_badge(client, published_event):
    response = client.get("/events/test-lan-party")
    assert b"LAN Party" in response.data


def test_event_detail_shows_board_game_badge(client, past_event):
    response = client.get("/events/past-board-game-night")
    assert response.status_code == 200
    assert b"Board Game Night" in response.data


def test_event_detail_shows_login_to_register_when_logged_out(client, published_event, ticket_type):
    response = client.get("/events/test-lan-party")
    assert response.status_code == 200
    assert b"Log in to Register" in response.data


def test_event_detail_shows_register_button_for_verified_user(client, regular_user, published_event, ticket_type):
    client.post("/login", data={"email": regular_user.email, "password": "userpass123"})
    response = client.get("/events/test-lan-party")
    assert response.status_code == 200
    assert b"Register Now" in response.data


def test_event_detail_shows_view_registration_when_registered(client, regular_user, published_event, ticket_type, registration):
    client.post("/login", data={"email": regular_user.email, "password": "userpass123"})
    response = client.get("/events/test-lan-party")
    assert response.status_code == 200
    assert b"View My Registration" in response.data


def test_event_detail_shows_attendee_list(client, regular_user, published_event, ticket_type, registration):
    response = client.get("/events/test-lan-party")
    assert response.status_code == 200
    assert b"Attendees" in response.data
    assert b"Regular" in response.data


def test_seed_event_command_idempotent(app):
    runner = app.test_cli_runner()
    result1 = runner.invoke(args=["seed-event"])
    assert "Seeded event" in result1.output

    result2 = runner.invoke(args=["seed-event"])
    assert "already exists" in result2.output

    assert Event.query.count() == 1


def test_event_detail_404_for_archived(client):
    from datetime import datetime
    event = Event(
        name="Old LAN Party",
        slug="old-lan-party",
        type="lan",
        status="archived",
        start_datetime=datetime(2024, 3, 1, 18, 0, 0),
        end_datetime=datetime(2024, 3, 3, 18, 0, 0),
        location="Old Venue",
        seating_enabled=False,
        registration_open=False,
    )
    _db.session.add(event)
    _db.session.commit()

    response = client.get("/events/old-lan-party")
    assert response.status_code == 404


def test_attendee_list_hides_last_name(client, regular_user, published_event, ticket_type, registration):
    regular_user.first_name = "Regular"
    regular_user.last_name = "Lastname"
    _db.session.commit()
    response = client.get("/events/test-lan-party")
    assert response.status_code == 200
    assert b"Regular" in response.data
    assert b"Lastname" not in response.data
