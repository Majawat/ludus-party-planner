"""Tests for the v1.5 data-model features:
- Event.collect_emergency_contacts (emergency contact decoupled from lodging)
- PotluckItem.event_date (per-day potluck)
- GameSuggestion play_style / system_requirements / notes + detail modal
"""
from datetime import timedelta
from uuid import uuid4

from models import (
    Event, GameSuggestion, GameSuggestionVote, PotluckItem, Registration,
    db, utcnow,
)


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# --- Emergency contact toggle ---------------------------------------------

def test_emergency_fields_shown_when_flag_set(client, regular_user, published_event, ticket_type, app):
    published_event.collect_emergency_contacts = True
    db.session.commit()
    _login(client, regular_user)
    resp = client.get(f"/events/{published_event.slug}/register")
    assert resp.status_code == 200
    assert b"Emergency Contact" in resp.data


def test_emergency_fields_hidden_when_flag_unset(client, regular_user, published_event, ticket_type, app):
    assert published_event.collect_emergency_contacts is False
    _login(client, regular_user)
    resp = client.get(f"/events/{published_event.slug}/register")
    assert resp.status_code == 200
    assert b"Emergency Contact" not in resp.data


def test_admin_sets_collect_emergency_contacts_on_edit(client, admin_user, published_event, app):
    _login(client, admin_user)
    resp = client.post(f"/admin/events/{published_event.id}/edit", data={
        "name": published_event.name, "slug": published_event.slug,
        "type": "lan", "status": "published", "location": "Test Venue",
        "start_datetime": published_event.start_datetime.strftime("%Y-%m-%dT%H:%M"),
        "end_datetime": published_event.end_datetime.strftime("%Y-%m-%dT%H:%M"),
        "collect_emergency_contacts": "y",
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.get(Event, published_event.id).collect_emergency_contacts is True


# --- Potluck per-day -------------------------------------------------------

def test_potluck_add_saves_valid_event_date(client, regular_user, registration, published_event, app):
    _login(client, regular_user)
    valid_day = (utcnow() + timedelta(days=91)).date()
    resp = client.post(f"/events/{published_event.slug}/my-registration/potluck/add", data={
        "description": "Nachos", "event_date": valid_day.isoformat(), "submit": "Add Item",
    }, follow_redirects=False)
    assert resp.status_code == 302
    item = PotluckItem.query.filter_by(registration_id=registration.id).first()
    assert item is not None and item.event_date == valid_day


def test_potluck_add_rejects_out_of_range_date(client, regular_user, registration, published_event, app):
    _login(client, regular_user)
    resp = client.post(f"/events/{published_event.slug}/my-registration/potluck/add", data={
        "description": "Soda", "event_date": (utcnow() + timedelta(days=300)).date().isoformat(),
    }, follow_redirects=False)
    assert resp.status_code == 302
    item = PotluckItem.query.filter_by(registration_id=registration.id, description="Soda").first()
    assert item is not None and item.event_date is None  # out-of-range -> stored as None


# --- Game suggestion detail fields + modal --------------------------------

def test_suggestion_saves_detail_fields(client, regular_user, registration, published_event, app):
    _login(client, regular_user)
    resp = client.post(f"/events/{published_event.slug}/suggestions/add", data={
        "game_name": "Root", "play_style": "competitive",
        "system_requirements": "Table space", "notes": "Bring the expansion",
        "submit": "Suggest Game",
    }, follow_redirects=False)
    assert resp.status_code == 302
    s = GameSuggestion.query.filter_by(event_id=published_event.id, game_name="Root").first()
    assert s is not None
    assert s.play_style == "competitive"
    assert s.system_requirements == "Table space"
    assert s.notes == "Bring the expansion"


def test_suggestion_detail_modal_route(client, regular_user, published_event, app):
    suggestion = GameSuggestion(
        event_id=published_event.id, suggested_by=regular_user.id,
        game_name="Wingspan", play_style="co-op", notes="Relaxing",
    )
    db.session.add(suggestion)
    db.session.flush()
    db.session.add(GameSuggestionVote(suggestion_id=suggestion.id, user_id=regular_user.id))
    db.session.commit()

    resp = client.get(f"/events/{published_event.slug}/suggestions/{suggestion.id}/detail")
    assert resp.status_code == 200
    assert b"Wingspan" in resp.data
    assert b"Relaxing" in resp.data
    # voter gamertag/public_name appears in the modal
    assert regular_user.public_name.encode() in resp.data
