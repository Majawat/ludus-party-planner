import json

from models import Event, SiteSettings, TicketType, db


ADMIN_ROUTES = [
    "/admin/",
    "/admin/settings",
    "/admin/events",
    "/admin/events/new",
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
        assert "16" in result.output

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
