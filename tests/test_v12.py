"""Tests for v1.2 features: game suggestions + upvoting, visual seat map."""
import json
import pytest
from datetime import datetime
from uuid import uuid4

from models import (
    GameSuggestion,
    GameSuggestionVote,
    Registration,
    TicketType,
    db as _db,
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
def suggestion(app, published_event, regular_user, registration):
    s = GameSuggestion(
        event_id=published_event.id,
        suggested_by=regular_user.id,
        game_name="Ticket to Ride",
    )
    _db.session.add(s)
    _db.session.commit()
    return s


# ---------------------------------------------------------------------------
# Game Suggestions — adding suggestions
# ---------------------------------------------------------------------------

class TestGameSuggestionAdd:
    def test_suggest_adds_to_db(self, client, regular_user, registration, published_event):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/add",
            data={"game_name": "Catan"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert GameSuggestion.query.filter_by(
            event_id=published_event.id, game_name="Catan"
        ).count() == 1

    def test_suggest_duplicate_rejected(self, client, regular_user, registration, published_event):
        _login(client, "user@example.com", "userpass123")
        data = {"game_name": "Catan"}
        client.post(f"/events/{published_event.slug}/suggestions/add", data=data)
        client.post(f"/events/{published_event.slug}/suggestions/add", data=data)
        assert GameSuggestion.query.filter_by(
            event_id=published_event.id, game_name="Catan"
        ).count() == 1

    def test_suggest_requires_registration(self, client, admin_user, published_event):
        # admin_user has no registration for this event
        _login(client, "admin@example.com", "adminpass123")
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/add",
            data={"game_name": "Risk"},
        )
        assert resp.status_code == 403

    def test_suggest_requires_login(self, client, published_event):
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/add",
            data={"game_name": "Risk"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_suggest_past_event_blocked(self, client, regular_user, past_registration, past_event):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{past_event.slug}/suggestions/add",
            data={"game_name": "Risk"},
        )
        assert resp.status_code == 403

    def test_suggest_cancelled_registration_blocked(
        self, client, regular_user, registration, published_event
    ):
        registration.status = "cancelled"
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/add",
            data={"game_name": "Risk"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Game Suggestions — voting
# ---------------------------------------------------------------------------

class TestGameSuggestionVote:
    def test_vote_adds_row(self, client, regular_user, registration, published_event, suggestion):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/{suggestion.id}/vote",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert GameSuggestionVote.query.filter_by(
            suggestion_id=suggestion.id, user_id=regular_user.id
        ).count() == 1

    def test_vote_toggle_removes(self, client, regular_user, registration, published_event, suggestion):
        _login(client, "user@example.com", "userpass123")
        url = f"/events/{published_event.slug}/suggestions/{suggestion.id}/vote"
        client.post(url)
        assert GameSuggestionVote.query.count() == 1
        client.post(url)
        assert GameSuggestionVote.query.count() == 0

    def test_vote_requires_registration(self, client, admin_user, published_event, suggestion):
        # admin_user has no registration for this event
        _login(client, "admin@example.com", "adminpass123")
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/{suggestion.id}/vote",
        )
        assert resp.status_code == 403

    def test_vote_requires_login(self, client, published_event, suggestion):
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/{suggestion.id}/vote",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_vote_past_event_blocked(
        self, client, regular_user, past_registration, past_event, app
    ):
        with app.app_context():
            past_suggestion = GameSuggestion(
                event_id=past_event.id,
                suggested_by=regular_user.id,
                game_name="Chess",
            )
            _db.session.add(past_suggestion)
            _db.session.commit()
            sid = past_suggestion.id

        _login(client, "user@example.com", "userpass123")
        resp = client.post(f"/events/{past_event.slug}/suggestions/{sid}/vote")
        assert resp.status_code == 403

    def test_vote_cancelled_registration_blocked(
        self, client, regular_user, registration, published_event, suggestion
    ):
        registration.status = "cancelled"
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/suggestions/{suggestion.id}/vote",
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Event detail page — suggestions display
# ---------------------------------------------------------------------------

class TestEventDetailSuggestions:
    def test_section_hidden_when_empty_and_not_eligible(self, client, published_event):
        # No suggestions, not logged in → section not rendered
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Game Suggestions" not in resp.data

    def test_section_visible_when_eligible_no_suggestions(
        self, client, regular_user, registration, published_event
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Game Suggestions" in resp.data

    def test_section_visible_with_suggestions_logged_out(
        self, client, published_event, suggestion
    ):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Game Suggestions" in resp.data
        assert b"Ticket to Ride" in resp.data

    def test_suggestions_sorted_by_vote_count_desc(
        self, client, regular_user, admin_user, registration, published_event, ticket_type, app
    ):
        # Create admin registration so admin can vote
        admin_reg = Registration(
            user_id=admin_user.id,
            event_id=published_event.id,
            ticket_type_id=ticket_type.id,
            status="confirmed",
            payment_status="unpaid",
            checkin_code=str(uuid4()),
        )
        _db.session.add(admin_reg)

        s1 = GameSuggestion(
            event_id=published_event.id,
            suggested_by=regular_user.id,
            game_name="Game Alpha",
        )
        s2 = GameSuggestion(
            event_id=published_event.id,
            suggested_by=regular_user.id,
            game_name="Game Beta",
        )
        _db.session.add_all([s1, s2])
        _db.session.commit()

        # Give s2 a vote → it should appear first
        vote = GameSuggestionVote(suggestion_id=s2.id, user_id=admin_user.id)
        _db.session.add(vote)
        _db.session.commit()

        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        pos_beta = resp.data.index(b"Game Beta")
        pos_alpha = resp.data.index(b"Game Alpha")
        assert pos_beta < pos_alpha

    def test_past_event_suggestions_visible_read_only(
        self, client, regular_user, past_registration, past_event, app
    ):
        with app.app_context():
            s = GameSuggestion(
                event_id=past_event.id,
                suggested_by=regular_user.id,
                game_name="Past Game",
            )
            _db.session.add(s)
            _db.session.commit()

        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{past_event.slug}")
        assert resp.status_code == 200
        assert b"Past Game" in resp.data
        # Should not show vote buttons (can_suggest is False for past events)
        assert b"suggestion_vote" not in resp.data or b"Suggest Game" not in resp.data


# ---------------------------------------------------------------------------
# Visual seat map — smoke tests
# ---------------------------------------------------------------------------

class TestVisualSeatMap:
    def test_user_seat_page_returns_200(
        self, client, regular_user, registration, published_event, seat
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}/seats")
        assert resp.status_code == 200

    def test_seat_page_shows_occupant_name(
        self, client, regular_user, admin_user, registration, published_event, ticket_type, seat
    ):
        # Create admin registration and claim the seat
        admin_reg = Registration(
            user_id=admin_user.id,
            event_id=published_event.id,
            ticket_type_id=ticket_type.id,
            status="confirmed",
            payment_status="unpaid",
            checkin_code=str(uuid4()),
        )
        admin_reg.seat_id = seat.id
        _db.session.add(admin_reg)
        _db.session.commit()

        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}/seats")
        assert resp.status_code == 200
        assert b"Admin" in resp.data  # admin_user.first_name is "Admin"

    def test_claiming_seat_updates_registration_seat_id(
        self, client, regular_user, registration, published_event, seat
    ):
        _login(client, "user@example.com", "userpass123")
        client.post(
            f"/events/{published_event.slug}/seats/claim",
            data={"seat_id": seat.id},
            follow_redirects=False,
        )
        _db.session.refresh(registration)
        assert registration.seat_id == seat.id

    def test_claiming_seat_via_htmx_returns_grid_partial(
        self, client, regular_user, registration, published_event, seat
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/seats/claim",
            data={"seat_id": seat.id},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert b"seat-grid" in resp.data

    def test_releasing_seat_via_htmx_returns_grid_partial(
        self, client, regular_user, registration, published_event, seat
    ):
        registration.seat_id = seat.id
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/seats/release",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert b"seat-grid" in resp.data


# ---------------------------------------------------------------------------
# Admin seat map — smoke tests
# ---------------------------------------------------------------------------

class TestAdminSeatMap:
    def test_admin_seat_page_returns_200(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        resp = client.get(f"/admin/events/{published_event.id}/seats")
        assert resp.status_code == 200

    def test_admin_seat_page_shows_grid_not_table(
        self, client, admin_user, published_event, seat
    ):
        _login(client, "admin@example.com", "adminpass123")
        resp = client.get(f"/admin/events/{published_event.id}/seats")
        assert resp.status_code == 200
        # Grid layout used, not table
        assert b"<table" not in resp.data
        assert b"grid" in resp.data

    def test_admin_seat_page_shows_occupant_link(
        self, client, admin_user, regular_user, registration, published_event, ticket_type, seat
    ):
        registration.seat_id = seat.id
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        resp = client.get(f"/admin/events/{published_event.id}/seats")
        assert resp.status_code == 200
        assert b"Regular" in resp.data  # regular_user.first_name is "Regular"
