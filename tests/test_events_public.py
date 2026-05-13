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


def test_event_detail_no_register_button(client, published_event):
    # Event registration is Phase 5 — the /register route for event sign-up must not exist yet
    response = client.get("/events/test-lan-party")
    assert b"/events/test-lan-party/register" not in response.data


def test_seed_event_command_idempotent(app):
    runner = app.test_cli_runner()
    result1 = runner.invoke(args=["seed-event"])
    assert "Seeded event" in result1.output

    result2 = runner.invoke(args=["seed-event"])
    assert "already exists" in result2.output

    assert Event.query.count() == 1
