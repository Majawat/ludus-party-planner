"""Tests for v1.3 remaining features: activity logging and location link."""
import json
import pytest
from unittest.mock import patch
from uuid import uuid4

import activity
from models import ActivityLog, Event, Registration, TicketType, db as _db, utcnow


def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ticket_for_log(app, published_event):
    tt = TicketType(
        event_id=published_event.id,
        name="Log Test Pass",
        price=0.00,
        quantity_total=10,
        seatable=False,
        includes_lodging=False,
        valid_days=json.dumps(["2026-08-07"]),
        max_per_user=1,
        is_active=True,
    )
    _db.session.add(tt)
    _db.session.commit()
    return tt


@pytest.fixture()
def reg_for_log(app, regular_user, published_event, ticket_for_log):
    reg = Registration(
        user_id=regular_user.id,
        event_id=published_event.id,
        ticket_type_id=ticket_for_log.id,
        status="confirmed",
        payment_status="unpaid",
        checkin_code=str(uuid4()),
    )
    _db.session.add(reg)
    _db.session.commit()
    return reg


# ---------------------------------------------------------------------------
# Test 1: log() creates an ActivityLog entry
# ---------------------------------------------------------------------------

def test_log_creates_entry(app, admin_user):
    with app.test_request_context("/admin/"):
        from flask_login import login_user
        login_user(admin_user)
        activity.log("event.created", "event", 42, {"name": "Test"})
        _db.session.commit()

    with app.app_context():
        entry = ActivityLog.query.first()
        assert entry is not None
        assert entry.action == "event.created"
        assert entry.target_type == "event"
        assert entry.target_id == 42
        assert entry.user_id == admin_user.id
        assert json.loads(entry.details) == {"name": "Test"}


# ---------------------------------------------------------------------------
# Test 2: log() fails silently on DB error
# ---------------------------------------------------------------------------

def test_log_fails_silently(app, admin_user):
    with app.test_request_context("/admin/"):
        from flask_login import login_user
        login_user(admin_user)
        with patch("models.db.session.add", side_effect=Exception("db error")):
            activity.log("event.created", "event", 1)
            # must not raise


# ---------------------------------------------------------------------------
# Test 3: /admin/logs returns 200 for admin
# ---------------------------------------------------------------------------

def test_admin_logs_page_returns_200(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    resp = client.get("/admin/logs")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test 4: /admin/logs returns 403 for non-admin
# ---------------------------------------------------------------------------

def test_admin_logs_page_403_for_non_admin(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    resp = client.get("/admin/logs")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 5: /admin/logs filters by action type
# ---------------------------------------------------------------------------

def test_admin_logs_filter_by_action(app, client, admin_user):
    with app.app_context():
        _db.session.add(ActivityLog(action="event.created", target_type="event", target_id=1))
        _db.session.add(ActivityLog(action="event.updated", target_type="event", target_id=1))
        _db.session.commit()

    _login(client, "admin@example.com", "adminpass123")
    resp = client.get("/admin/logs?action=event.created")
    assert resp.status_code == 200
    # Table rows wrap the action in <code class="text-xs">; dropdown uses <option>
    assert b'<code class="text-xs">event.created</code>' in resp.data
    assert b'<code class="text-xs">event.updated</code>' not in resp.data


# ---------------------------------------------------------------------------
# Test 6: mark-paid route creates ActivityLog entry
# ---------------------------------------------------------------------------

def test_mark_paid_creates_log_entry(client, admin_user, published_event, reg_for_log):
    _login(client, "admin@example.com", "adminpass123")
    resp = client.post(
        f"/admin/events/{published_event.id}/registrations/{reg_for_log.id}/mark-paid",
        data={"paid-payment_method": "cash"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    entry = ActivityLog.query.filter_by(action="registration.marked_paid").first()
    assert entry is not None
    assert entry.target_id == reg_for_log.id


# ---------------------------------------------------------------------------
# Test 7: log() calls flush, not commit
# ---------------------------------------------------------------------------

def test_log_flush_not_commit(app, admin_user):
    with app.test_request_context("/admin/"):
        from flask_login import login_user
        login_user(admin_user)
        with patch.object(_db.session, "commit") as mock_commit:
            activity.log("event.created", "event", 1)
            mock_commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 8: event detail page renders location as Google Maps link
# ---------------------------------------------------------------------------

def test_event_detail_location_is_link(client, published_event):
    resp = client.get(f"/events/{published_event.slug}")
    assert resp.status_code == 200
    assert b"google.com/maps" in resp.data


# ---------------------------------------------------------------------------
# Test 9: location link works with GPS coordinates
# ---------------------------------------------------------------------------

def test_location_link_works_with_coordinates(app, client):
    with app.app_context():
        event = Event(
            name="Coords Event",
            slug="coords-event",
            type="lan",
            status="published",
            short_description="GPS test.",
            start_datetime=utcnow(),
            end_datetime=utcnow(),
            location="38.8976,-77.0366",
            seating_enabled=False,
            registration_open=False,
        )
        _db.session.add(event)
        _db.session.commit()
        slug = event.slug

    resp = client.get(f"/events/{slug}")
    assert resp.status_code == 200
    assert b"38.8976" in resp.data
    assert b"google.com/maps" in resp.data


# ---------------------------------------------------------------------------
# Test 10: navbar dropdown shows user name and profile link when authenticated
# ---------------------------------------------------------------------------

def test_navbar_shows_dropdown_when_authenticated(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    resp = client.get("/")
    assert resp.status_code == 200
    assert regular_user.name.encode() in resp.data
    assert b"/account" in resp.data


# ---------------------------------------------------------------------------
# Test 11: navbar shows Admin Panel link for admins
# ---------------------------------------------------------------------------

def test_navbar_shows_admin_link_for_admin(client, admin_user):
    _login(client, "admin@example.com", "adminpass123")
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/admin/" in resp.data
    assert b"Admin Panel" in resp.data


# ---------------------------------------------------------------------------
# Test 12: navbar hides Admin Panel link for regular users
# ---------------------------------------------------------------------------

def test_navbar_hides_admin_link_for_regular_user(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Admin Panel" not in resp.data


# ---------------------------------------------------------------------------
# Test 13: dashboard shows a My Profile card linking to /account
# ---------------------------------------------------------------------------

def test_dashboard_shows_profile_card(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"My Profile" in resp.data
    assert b"/account" in resp.data


# ---------------------------------------------------------------------------
# Test 14: POST /logout redirects and ends the session
# ---------------------------------------------------------------------------

def test_logout_via_post_logs_out_user(client, regular_user):
    _login(client, "user@example.com", "userpass123")
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    resp2 = client.get("/dashboard", follow_redirects=False)
    assert resp2.status_code == 302


# ---------------------------------------------------------------------------
# Test 15: GET /logout is rejected with 405
# ---------------------------------------------------------------------------

def test_logout_via_get_is_rejected(client, regular_user):
    # GET /logout must return 405 — logout is a state-changing action
    # that must be protected from CSRF via image tags or link-based redirects.
    _login(client, "user@example.com", "userpass123")
    resp = client.get("/logout")
    assert resp.status_code == 405
