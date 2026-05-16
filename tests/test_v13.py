"""Tests for v1.3 features: Challonge tournament integration."""
import pytest
import requests as http_requests
from unittest.mock import MagicMock, patch
from uuid import uuid4

from models import (
    SiteSettings, Tournament, TournamentParticipant,
    Registration, TicketType,
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


def _make_http_error(status_code=500, text="Server Error"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    err = http_requests.HTTPError(response=resp)
    return err


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def challonge_settings(app):
    """Seed Challonge credentials into site settings."""
    with app.app_context():
        SiteSettings.set("challonge_api_key", "test-api-key")
        SiteSettings.set("challonge_username", "testuser")
        _db.session.commit()


@pytest.fixture()
def tournament(app, published_event):
    t = Tournament(
        event_id=published_event.id,
        name="Test Bracket",
        game_name="Street Fighter 6",
        format="single elimination",
        challonge_id=12345,
        challonge_url_slug="testuser-test-lan-party-test-bracket-1234",
        challonge_full_url="https://challonge.com/testuser-test-lan-party-test-bracket-1234",
        status="pending",
        sign_ups_open=True,
    )
    _db.session.add(t)
    _db.session.commit()
    return t


# ---------------------------------------------------------------------------
# Admin — Create tournament
# ---------------------------------------------------------------------------

class TestAdminTournamentCreate:

    def test_create_success(self, client, admin_user, challonge_settings, published_event):
        _login(client, "admin@example.com", "adminpass123")
        mock_return = {
            "tournament": {
                "id": 99,
                "url": "testuser-test-lan-party-sf6-1234",
                "full_challonge_url": "https://challonge.com/testuser-test-lan-party-sf6-1234",
            }
        }
        with patch("challonge._api", return_value=mock_return):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/new",
                data={
                    "name": "SF6 Tournament",
                    "game_name": "Street Fighter 6",
                    "format": "single elimination",
                    "sign_ups_open": "y",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        t = Tournament.query.filter_by(event_id=published_event.id).first()
        assert t is not None
        assert t.challonge_id == 99
        assert t.challonge_full_url == "https://challonge.com/testuser-test-lan-party-sf6-1234"
        assert t.name == "SF6 Tournament"

    def test_create_api_error_no_db_record(self, client, admin_user, challonge_settings, published_event):
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", side_effect=http_requests.RequestException("timeout")):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/new",
                data={
                    "name": "Bad Tourney",
                    "game_name": "Chess",
                    "format": "round robin",
                },
                follow_redirects=True,
            )
        assert resp.status_code == 200
        assert Tournament.query.count() == 0

    def test_create_redirect_when_challonge_not_configured(self, client, admin_user, published_event):
        _login(client, "admin@example.com", "adminpass123")
        resp = client.get(
            f"/admin/events/{published_event.id}/tournaments/new",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Configure Challonge" in resp.data

    def test_list_page_loads(self, client, admin_user, published_event, tournament):
        _login(client, "admin@example.com", "adminpass123")
        resp = client.get(f"/admin/events/{published_event.id}/tournaments")
        assert resp.status_code == 200
        assert b"Test Bracket" in resp.data


# ---------------------------------------------------------------------------
# Admin — Add participants
# ---------------------------------------------------------------------------

class TestAdminTournamentParticipants:

    def test_add_participants_from_registrations(
        self, client, admin_user, challonge_settings, published_event, tournament, registration
    ):
        _login(client, "admin@example.com", "adminpass123")
        api_return = [{"participant": {"id": 55, "name": "Regular"}}]
        with patch("challonge._api", return_value=api_return):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/add-participants",
                data={"registration_ids": str(registration.id)},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        p = TournamentParticipant.query.filter_by(
            tournament_id=tournament.id, registration_id=registration.id
        ).first()
        assert p is not None
        assert p.challonge_participant_id == 55
        assert p.display_name == "Regular"

    def test_add_manual_participant(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        _login(client, "admin@example.com", "adminpass123")
        api_return = [{"participant": {"id": 77, "name": "Guest Player"}}]
        with patch("challonge._api", return_value=api_return):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/add-manual",
                data={"display_name": "Guest Player"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        p = TournamentParticipant.query.filter_by(
            tournament_id=tournament.id, registration_id=None
        ).first()
        assert p is not None
        assert p.display_name == "Guest Player"
        assert p.challonge_participant_id == 77

    def test_remove_participant(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        p = TournamentParticipant(
            tournament_id=tournament.id, display_name="Alice", challonge_participant_id=10
        )
        _db.session.add(p)
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", return_value={}):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/remove-participant/{p.id}",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert TournamentParticipant.query.count() == 0

    def test_remove_blocked_when_underway(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        tournament.status = "underway"
        _db.session.commit()
        p = TournamentParticipant(tournament_id=tournament.id, display_name="Alice")
        _db.session.add(p)
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        resp = client.post(
            f"/admin/events/{published_event.id}/tournaments/{tournament.id}/remove-participant/{p.id}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert TournamentParticipant.query.count() == 1


# ---------------------------------------------------------------------------
# Admin — Start / Reset
# ---------------------------------------------------------------------------

class TestAdminTournamentStart:

    def test_start_success(self, client, admin_user, challonge_settings, published_event, tournament):
        for name in ["Alice", "Bob"]:
            _db.session.add(TournamentParticipant(tournament_id=tournament.id, display_name=name))
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", return_value={"tournament": {"state": "underway"}}):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/start",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        _db.session.refresh(tournament)
        assert tournament.status == "underway"
        assert tournament.sign_ups_open is False

    def test_start_blocked_too_few_participants(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        _db.session.add(TournamentParticipant(tournament_id=tournament.id, display_name="Solo"))
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        resp = client.post(
            f"/admin/events/{published_event.id}/tournaments/{tournament.id}/start",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        _db.session.refresh(tournament)
        assert tournament.status == "pending"

    def test_reset_sets_status_pending(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        tournament.status = "underway"
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", return_value={"tournament": {"state": "pending"}}):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/reset",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        _db.session.refresh(tournament)
        assert tournament.status == "pending"


# ---------------------------------------------------------------------------
# Admin — Match reporting
# ---------------------------------------------------------------------------

class TestAdminMatchReport:

    def test_report_match_htmx_success(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        tournament.status = "underway"
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", return_value={"match": {"state": "complete"}}):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/matches/77/report",
                data={"winner_id": "1", "scores_csv": "2-1"},
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert b"Result recorded" in resp.data

    def test_report_match_htmx_api_error(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        tournament.status = "underway"
        _db.session.commit()
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", side_effect=http_requests.RequestException("network error")):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/matches/77/report",
                data={"winner_id": "1", "scores_csv": "2-1"},
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert b"Error" in resp.data


# ---------------------------------------------------------------------------
# Admin — Delete
# ---------------------------------------------------------------------------

class TestAdminTournamentDelete:

    def test_delete_removes_db_record_and_calls_api(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", return_value={}) as mock_api:
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/delete",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert Tournament.query.count() == 0
        mock_api.assert_called()

    def test_delete_proceeds_even_if_challonge_fails(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        _login(client, "admin@example.com", "adminpass123")
        with patch("challonge._api", side_effect=http_requests.RequestException("not found")):
            resp = client.post(
                f"/admin/events/{published_event.id}/tournaments/{tournament.id}/delete",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert Tournament.query.count() == 0


# ---------------------------------------------------------------------------
# Attendee self-registration
# ---------------------------------------------------------------------------

class TestAttendeeTournamentSignup:

    def test_signup_success(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        _login(client, "user@example.com", "userpass123")
        api_return = [{"participant": {"id": 88, "name": "Regular"}}]
        with patch("challonge._api", return_value=api_return):
            resp = client.post(
                f"/events/{published_event.slug}/tournaments/{tournament.id}/signup",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        p = TournamentParticipant.query.filter_by(
            tournament_id=tournament.id, registration_id=registration.id
        ).first()
        assert p is not None
        assert p.display_name == "Regular"
        assert p.challonge_participant_id == 88

    def test_signup_blocked_not_registered(
        self, client, admin_user, challonge_settings, published_event, tournament
    ):
        # admin_user has no registration for published_event
        _login(client, "admin@example.com", "adminpass123")
        resp = client.post(
            f"/events/{published_event.slug}/tournaments/{tournament.id}/signup",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert TournamentParticipant.query.count() == 0

    def test_signup_blocked_already_signed_up(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        existing = TournamentParticipant(
            tournament_id=tournament.id,
            registration_id=registration.id,
            display_name="Regular",
        )
        _db.session.add(existing)
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        with patch("challonge._api", return_value=[{"participant": {"id": 99, "name": "Regular"}}]):
            resp = client.post(
                f"/events/{published_event.slug}/tournaments/{tournament.id}/signup",
                follow_redirects=True,
            )
        assert resp.status_code == 200
        # Still only one participant
        assert TournamentParticipant.query.filter_by(tournament_id=tournament.id).count() == 1

    def test_signup_blocked_sign_ups_closed(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        tournament.sign_ups_open = False
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/tournaments/{tournament.id}/signup",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert TournamentParticipant.query.count() == 0

    def test_signup_degrades_gracefully_on_api_error(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        _login(client, "user@example.com", "userpass123")
        with patch("challonge._api", side_effect=http_requests.RequestException("timeout")):
            resp = client.post(
                f"/events/{published_event.slug}/tournaments/{tournament.id}/signup",
                follow_redirects=False,
            )
        # Should still succeed locally — degrade gracefully
        assert resp.status_code == 302
        p = TournamentParticipant.query.filter_by(tournament_id=tournament.id).first()
        assert p is not None
        assert p.challonge_participant_id is None


class TestAttendeeTournamentWithdraw:

    def test_withdraw_success(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        p = TournamentParticipant(
            tournament_id=tournament.id,
            registration_id=registration.id,
            display_name="Regular",
            challonge_participant_id=42,
        )
        _db.session.add(p)
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        with patch("challonge._api", return_value={}):
            resp = client.post(
                f"/events/{published_event.slug}/tournaments/{tournament.id}/withdraw",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert TournamentParticipant.query.count() == 0

    def test_withdraw_blocked_when_underway(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        tournament.status = "underway"
        _db.session.commit()
        p = TournamentParticipant(
            tournament_id=tournament.id,
            registration_id=registration.id,
            display_name="Regular",
        )
        _db.session.add(p)
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/tournaments/{tournament.id}/withdraw",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert TournamentParticipant.query.count() == 1

    def test_withdraw_not_signed_up(
        self, client, regular_user, challonge_settings, published_event, tournament, registration
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/events/{published_event.slug}/tournaments/{tournament.id}/withdraw",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Flash message shown, no crash


# ---------------------------------------------------------------------------
# Public event detail page
# ---------------------------------------------------------------------------

class TestPublicTournamentSection:

    def test_section_hidden_when_no_tournaments(self, client, published_event):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Tournaments" not in resp.data

    def test_section_visible_with_tournament(self, client, published_event, tournament):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Tournaments" in resp.data
        assert b"Test Bracket" in resp.data
        assert b"Street Fighter 6" in resp.data

    def test_iframe_shown_when_underway(self, client, published_event, tournament):
        tournament.status = "underway"
        _db.session.commit()
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"iframe" in resp.data
        assert tournament.challonge_url_slug.encode() in resp.data

    def test_signup_button_shown_to_confirmed_registrant(
        self, client, regular_user, published_event, tournament, registration
    ):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Sign Up on My Registration" in resp.data

    def test_signup_button_hidden_when_sign_ups_closed(
        self, client, regular_user, published_event, tournament, registration
    ):
        tournament.sign_ups_open = False
        _db.session.commit()
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/events/{published_event.slug}")
        assert b"Sign Up on My Registration" not in resp.data

    def test_no_embed_when_pending(self, client, published_event, tournament):
        resp = client.get(f"/events/{published_event.slug}")
        assert b"iframe" not in resp.data


# ---------------------------------------------------------------------------
# Security: admin tournament routes require admin
# ---------------------------------------------------------------------------

class TestTournamentSecurity:

    def test_list_requires_admin(self, client, regular_user, published_event):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/admin/events/{published_event.id}/tournaments")
        assert resp.status_code == 403

    def test_new_requires_admin(self, client, regular_user, published_event):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/admin/events/{published_event.id}/tournaments/new")
        assert resp.status_code == 403

    def test_detail_requires_admin(self, client, regular_user, published_event, tournament):
        _login(client, "user@example.com", "userpass123")
        resp = client.get(f"/admin/events/{published_event.id}/tournaments/{tournament.id}")
        assert resp.status_code == 403

    def test_start_requires_admin(self, client, regular_user, published_event, tournament):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/admin/events/{published_event.id}/tournaments/{tournament.id}/start"
        )
        assert resp.status_code == 403

    def test_delete_requires_admin(self, client, regular_user, published_event, tournament):
        _login(client, "user@example.com", "userpass123")
        resp = client.post(
            f"/admin/events/{published_event.id}/tournaments/{tournament.id}/delete"
        )
        assert resp.status_code == 403

    def test_unauthenticated_redirected_to_login(self, client, published_event):
        resp = client.get(
            f"/admin/events/{published_event.id}/tournaments",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
