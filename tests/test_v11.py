"""Tests for v1.1 features: schedule, potluck, loaner equipment, announcements, check-in mode."""
import json
import pytest
from datetime import datetime
from uuid import uuid4

from models import (
    EventAnnouncement, EventScheduleItem, LoanerEquipment, LoanerRequest,
    PotluckItem, Registration, SiteSettings, TicketType, db as _db, utcnow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


@pytest.fixture()
def loaner_equipment(app):
    eq = LoanerEquipment(name="Gaming PC 1", specs="i7-12700, RTX 3060", is_available=True)
    _db.session.add(eq)
    _db.session.commit()
    return eq


@pytest.fixture()
def unavailable_equipment(app):
    eq = LoanerEquipment(name="Broken Laptop", specs="broken", is_available=False)
    _db.session.add(eq)
    _db.session.commit()
    return eq


# ---------------------------------------------------------------------------
# Feature 2: Event Schedule
# ---------------------------------------------------------------------------

class TestSchedule:
    def test_admin_schedule_list_returns_200(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.get(f"/admin/events/{published_event.id}/schedule")
        assert response.status_code == 200

    def test_admin_schedule_add_creates_item(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/schedule/add",
            data={
                "title": "Opening Ceremony",
                "description": "Welcome everyone",
                "starts_at": "2026-08-07T18:00",
                "ends_at": "2026-08-07T19:00",
                "display_order": "0",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        item = EventScheduleItem.query.filter_by(title="Opening Ceremony").first()
        assert item is not None
        assert item.event_id == published_event.id

    def test_admin_schedule_add_htmx_returns_partial(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/schedule/add",
            data={
                "title": "Game Tourney",
                "starts_at": "2026-08-08T14:00",
                "ends_at": "",
                "display_order": "1",
            },
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert b"Game Tourney" in response.data

    def test_admin_schedule_delete_removes_item(self, client, admin_user, published_event):
        item = EventScheduleItem(
            event_id=published_event.id,
            title="Midnight Snack",
            starts_at=datetime(2026, 8, 8, 0, 0),
        )
        _db.session.add(item)
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/schedule/{item.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert EventScheduleItem.query.get(item.id) is None

    def test_admin_schedule_delete_htmx_returns_empty(self, client, admin_user, published_event):
        item = EventScheduleItem(
            event_id=published_event.id,
            title="Deleted",
            starts_at=datetime(2026, 8, 8, 10, 0),
        )
        _db.session.add(item)
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/schedule/{item.id}/delete",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert response.data == b""

    def test_public_event_detail_shows_schedule(self, client, published_event):
        item = EventScheduleItem(
            event_id=published_event.id,
            title="LAN Tournament",
            starts_at=datetime(2026, 8, 8, 13, 0),
        )
        _db.session.add(item)
        _db.session.commit()

        response = client.get(f"/events/{published_event.slug}")
        assert response.status_code == 200
        assert b"LAN Tournament" in response.data

    def test_public_event_detail_hides_schedule_section_when_empty(self, client, published_event):
        response = client.get(f"/events/{published_event.slug}")
        assert response.status_code == 200
        assert b"Schedule" not in response.data

    def test_admin_schedule_requires_admin(self, client, regular_user, published_event):
        _login(client, "user@example.com", "userpass123")
        response = client.get(f"/admin/events/{published_event.id}/schedule")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Feature 3: Potluck Signup
# ---------------------------------------------------------------------------

class TestPotluck:
    def test_potluck_add_creates_item(self, client, regular_user, registration, published_event):
        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/events/{published_event.slug}/my-registration/potluck/add",
            data={"description": "Chips and salsa"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        item = PotluckItem.query.filter_by(description="Chips and salsa").first()
        assert item is not None
        assert item.registration_id == registration.id

    def test_potluck_add_requires_login(self, client, published_event):
        response = client.post(
            f"/events/{published_event.slug}/my-registration/potluck/add",
            data={"description": "Cookies"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_potluck_add_rejects_cancelled_registration(self, client, regular_user, registration, published_event):
        registration.status = "cancelled"
        _db.session.commit()

        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/events/{published_event.slug}/my-registration/potluck/add",
            data={"description": "Drinks"},
        )
        assert response.status_code == 403

    def test_potluck_add_rejects_past_event(self, client, regular_user, past_registration, past_event):
        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/events/{past_event.slug}/my-registration/potluck/add",
            data={"description": "Cake"},
        )
        assert response.status_code == 403

    def test_potluck_delete_removes_item(self, client, regular_user, registration, published_event):
        item = PotluckItem(
            event_id=published_event.id,
            registration_id=registration.id,
            description="Soda",
        )
        _db.session.add(item)
        _db.session.commit()

        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/events/{published_event.slug}/my-registration/potluck/{item.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert PotluckItem.query.get(item.id) is None

    def test_potluck_delete_rejects_wrong_user(self, client, admin_user, registration, published_event):
        """Admin user (no registration) cannot delete another user's potluck item.
        Gets 404 because they have no registration for the event."""
        item = PotluckItem(
            event_id=published_event.id,
            registration_id=registration.id,
            description="Pizza",
        )
        _db.session.add(item)
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/events/{published_event.slug}/my-registration/potluck/{item.id}/delete",
        )
        # No registration for admin → 404; item untouched
        assert response.status_code == 404
        assert _db.session.get(PotluckItem, item.id) is not None

    def test_public_event_detail_shows_potluck(self, client, registration, published_event):
        item = PotluckItem(
            event_id=published_event.id,
            registration_id=registration.id,
            description="Guacamole",
        )
        _db.session.add(item)
        _db.session.commit()

        response = client.get(f"/events/{published_event.slug}")
        assert response.status_code == 200
        assert b"Guacamole" in response.data

    def test_public_event_detail_hides_potluck_when_empty(self, client, published_event):
        response = client.get(f"/events/{published_event.slug}")
        assert response.status_code == 200
        assert b"Potluck" not in response.data


# ---------------------------------------------------------------------------
# Feature 4: Loaner Equipment
# ---------------------------------------------------------------------------

class TestLoanerEquipment:
    def test_equipment_list_returns_200(self, client, admin_user):
        _login(client, "admin@example.com", "adminpass123")
        response = client.get("/admin/equipment")
        assert response.status_code == 200

    def test_equipment_list_requires_admin(self, client, regular_user):
        _login(client, "user@example.com", "userpass123")
        response = client.get("/admin/equipment")
        assert response.status_code == 403

    def test_equipment_add_creates_equipment(self, client, admin_user):
        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            "/admin/equipment/add",
            data={
                "name": "Dell Laptop",
                "specs": "i5, 8GB RAM",
                "description": "",
                "is_available": "y",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        eq = LoanerEquipment.query.filter_by(name="Dell Laptop").first()
        assert eq is not None
        assert eq.is_available is True

    def test_equipment_toggle_availability(self, client, admin_user, loaner_equipment):
        _login(client, "admin@example.com", "adminpass123")
        client.post(f"/admin/equipment/{loaner_equipment.id}/toggle")
        _db.session.refresh(loaner_equipment)
        assert loaner_equipment.is_available is False

        client.post(f"/admin/equipment/{loaner_equipment.id}/toggle")
        _db.session.refresh(loaner_equipment)
        assert loaner_equipment.is_available is True

    def test_loaner_request_creates_and_syncs(self, client, regular_user, registration, published_event, loaner_equipment):
        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/events/{published_event.slug}/my-registration/loaner",
            data={"equipment_id": str(loaner_equipment.id)},
            follow_redirects=False,
        )
        assert response.status_code == 302
        req = LoanerRequest.query.filter_by(registration_id=registration.id).first()
        assert req is not None
        assert req.equipment_id == loaner_equipment.id
        assert req.status == "requested"
        _db.session.refresh(registration)
        assert registration.needs_loaner is True

    def test_loaner_request_no_preference(self, client, regular_user, registration, published_event):
        _login(client, "user@example.com", "userpass123")
        client.post(
            f"/events/{published_event.slug}/my-registration/loaner",
            data={"equipment_id": "0"},
        )
        req = LoanerRequest.query.filter_by(registration_id=registration.id).first()
        assert req is not None
        assert req.equipment_id is None
        _db.session.refresh(registration)
        assert registration.needs_loaner is True

    def test_loaner_request_cancel_removes_request_and_syncs(
        self, client, regular_user, registration, published_event, loaner_equipment
    ):
        # First create a request
        req = LoanerRequest(
            registration_id=registration.id,
            equipment_id=loaner_equipment.id,
            status="requested",
        )
        registration.needs_loaner = True
        _db.session.add(req)
        _db.session.commit()

        _login(client, "user@example.com", "userpass123")
        client.post(
            f"/events/{published_event.slug}/my-registration/loaner",
            data={"equipment_id": "none"},
        )
        assert LoanerRequest.query.filter_by(registration_id=registration.id).count() == 0
        _db.session.refresh(registration)
        assert registration.needs_loaner is False

    def test_loaner_request_rejects_past_event(self, client, regular_user, past_registration, past_event):
        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/events/{past_event.slug}/my-registration/loaner",
            data={"equipment_id": "0"},
        )
        assert response.status_code == 403

    def test_admin_loaners_list_returns_200(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.get(f"/admin/events/{published_event.id}/loaners")
        assert response.status_code == 200

    def test_admin_loaners_list_requires_admin(self, client, regular_user, published_event):
        _login(client, "user@example.com", "userpass123")
        response = client.get(f"/admin/events/{published_event.id}/loaners")
        assert response.status_code == 403

    def test_admin_loaner_approve(self, client, admin_user, registration, published_event):
        req = LoanerRequest(registration_id=registration.id, status="requested")
        _db.session.add(req)
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        client.post(f"/admin/events/{published_event.id}/loaners/{req.id}/approve")
        _db.session.refresh(req)
        assert req.status == "approved"

    def test_admin_loaner_deny(self, client, admin_user, registration, published_event):
        req = LoanerRequest(registration_id=registration.id, status="requested")
        _db.session.add(req)
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        client.post(f"/admin/events/{published_event.id}/loaners/{req.id}/deny")
        _db.session.refresh(req)
        assert req.status == "denied"


# ---------------------------------------------------------------------------
# Feature 5: Event Announcements
# ---------------------------------------------------------------------------

class TestAnnouncements:
    def test_announcement_add_creates_announcement(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/announcements/add",
            data={"title": "Important Update", "body": "The event starts at 6pm."},
            follow_redirects=False,
        )
        assert response.status_code == 302
        ann = EventAnnouncement.query.filter_by(title="Important Update").first()
        assert ann is not None
        assert ann.event_id == published_event.id
        assert ann.created_by == admin_user.id

    def test_announcement_add_requires_admin(self, client, regular_user, published_event):
        _login(client, "user@example.com", "userpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/announcements/add",
            data={"title": "Hack", "body": "body"},
        )
        assert response.status_code == 403

    def test_announcement_delete_removes_announcement(self, client, admin_user, published_event):
        ann = EventAnnouncement(
            event_id=published_event.id,
            title="Old News",
            body="Whatever.",
            created_by=admin_user.id,
        )
        _db.session.add(ann)
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        client.post(
            f"/admin/events/{published_event.id}/announcements/{ann.id}/delete",
        )
        assert EventAnnouncement.query.get(ann.id) is None

    def test_public_event_detail_shows_announcements(self, client, admin_user, published_event):
        ann = EventAnnouncement(
            event_id=published_event.id,
            title="Venue Change",
            body="We moved to the new hall!",
            created_by=admin_user.id,
        )
        _db.session.add(ann)
        _db.session.commit()

        response = client.get(f"/events/{published_event.slug}")
        assert response.status_code == 200
        assert b"Venue Change" in response.data
        assert b"We moved to the new hall" in response.data

    def test_public_event_detail_hides_announcements_when_empty(self, client, published_event):
        response = client.get(f"/events/{published_event.slug}")
        assert response.status_code == 200
        assert b"Announcements" not in response.data


# ---------------------------------------------------------------------------
# Feature 6: Check-in Mode
# ---------------------------------------------------------------------------

class TestCheckinMode:
    def test_checkin_page_returns_200(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.get(f"/admin/events/{published_event.id}/checkin")
        assert response.status_code == 200
        assert b"Check-in" in response.data

    def test_checkin_page_requires_admin(self, client, regular_user, published_event):
        _login(client, "user@example.com", "userpass123")
        response = client.get(f"/admin/events/{published_event.id}/checkin")
        assert response.status_code == 403

    def test_checkin_page_requires_login(self, client, published_event):
        response = client.get(f"/admin/events/{published_event.id}/checkin")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_checkin_search_returns_partial(self, client, admin_user, registration, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.get(
            f"/admin/events/{published_event.id}/checkin/search?q=Regular",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert b"Regular" in response.data

    def test_checkin_search_empty_query_returns_empty_list(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.get(f"/admin/events/{published_event.id}/checkin/search?q=")
        assert response.status_code == 200
        assert b"Regular" not in response.data

    def test_checkin_search_excludes_cancelled(self, client, admin_user, registration, published_event):
        registration.status = "cancelled"
        _db.session.commit()

        _login(client, "admin@example.com", "adminpass123")
        response = client.get(
            f"/admin/events/{published_event.id}/checkin/search?q=Regular",
        )
        assert b"Regular" not in response.data

    def test_checkin_mark_checked_in_via_htmx(self, client, admin_user, registration, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/registrations/{registration.id}/check-in",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert b"Checked" in response.data
        _db.session.refresh(registration)
        assert registration.checked_in_at is not None

    def test_checkin_mark_checked_in_without_htmx_redirects(self, client, admin_user, registration, published_event):
        _login(client, "admin@example.com", "adminpass123")
        response = client.post(
            f"/admin/events/{published_event.id}/registrations/{registration.id}/check-in",
            follow_redirects=False,
        )
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Admin security sweep — new routes added to ADMIN_ROUTES
# ---------------------------------------------------------------------------

NEW_ADMIN_ROUTES = [
    "/admin/equipment",
    "/admin/events/1/schedule",
    "/admin/events/1/loaners",
    "/admin/events/1/checkin",
]


def test_new_admin_routes_redirect_unauthenticated(client, published_event):
    for route in NEW_ADMIN_ROUTES:
        # Use published_event.id instead of "1" to match actual DB id
        actual = route.replace("/1/", f"/{published_event.id}/").replace("/1", f"/{published_event.id}")
        response = client.get(actual)
        assert response.status_code == 302, f"{actual} should redirect unauthenticated"
        assert "/login" in response.headers["Location"], f"{actual} should redirect to login"


def test_new_admin_routes_return_403_for_non_admin(client, regular_user, published_event):
    _login(client, "user@example.com", "userpass123")
    for route in NEW_ADMIN_ROUTES:
        actual = route.replace("/1/", f"/{published_event.id}/").replace("/1", f"/{published_event.id}")
        response = client.get(actual)
        assert response.status_code == 403, f"{actual} should return 403 for non-admin"


def test_new_admin_routes_return_200_for_admin(client, admin_user, published_event):
    _login(client, "admin@example.com", "adminpass123")
    for route in NEW_ADMIN_ROUTES:
        actual = route.replace("/1/", f"/{published_event.id}/").replace("/1", f"/{published_event.id}")
        response = client.get(actual)
        assert response.status_code == 200, f"{actual} should return 200 for admin"
