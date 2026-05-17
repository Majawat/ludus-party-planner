"""Tests for game_lookup module and /games/search route, plus enriched suggestion creation."""
import json
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
import xml.etree.ElementTree as ET

import requests as req

from game_lookup import search_bgg, get_bgg_game, get_itad_prices, search_steam, get_steam_game, search_games
from models import GameSuggestion, Registration, TicketType, db as _db


# ---------------------------------------------------------------------------
# Helper XML builders
# ---------------------------------------------------------------------------

_BGG_SEARCH_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<items total="2">
  <item type="boardgame" id="13">
    <name type="primary" value="Catan"/>
    <yearpublished value="1995"/>
  </item>
  <item type="boardgame" id="42">
    <name type="primary" value="Twilight Imperium"/>
  </item>
</items>"""

_BGG_THING_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<items>
  <item type="boardgame" id="13">
    <name type="primary" value="Catan"/>
    <description>Trade &amp; settle the isle of Catan.</description>
    <thumbnail>https://cf.geekdo-images.com/catan.jpg</thumbnail>
    <yearpublished value="1995"/>
    <minplayers value="3"/>
    <maxplayers value="4"/>
  </item>
</items>"""

_BGG_EMPTY_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<items total="0">
</items>"""

_STEAM_SEARCH_JSON = {
    "items": [
        {"id": 289070, "name": "Sid Meier's Civilization VI", "tiny_image": "https://cdn.steam/civ6.jpg"},
        {"id": 1091500, "name": "Cyberpunk 2077", "tiny_image": None},
    ]
}

_STEAM_APPDETAILS_JSON = {
    "289070": {
        "success": True,
        "data": {
            "name": "Sid Meier's Civilization VI",
            "short_description": "Explore a new land, research technology, build civilization.",
            "header_image": "https://cdn.steam/civ6_header.jpg",
        }
    }
}

_STEAM_APPDETAILS_FAIL_JSON = {
    "99999": {"success": False}
}


def _mock_response(content=None, json_data=None, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    if content is not None:
        mock.content = content
    if json_data is not None:
        mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# search_bgg unit tests
# ---------------------------------------------------------------------------

class TestSearchBGG:
    def test_returns_parsed_results(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=_BGG_SEARCH_XML)
            results = search_bgg("catan")
        assert len(results) == 2
        assert results[0]["id"] == "13"
        assert results[0]["name"] == "Catan"
        assert results[0]["year"] == "1995"
        assert results[0]["source"] == "bgg"
        assert results[0]["image"] is None
        assert results[1]["name"] == "Twilight Imperium"
        assert results[1]["year"] is None

    def test_returns_empty_on_request_exception(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("timeout")
            # search_bgg itself raises — caller (search_games) catches it
            with pytest.raises(req.RequestException):
                search_bgg("catan")

    def test_skips_items_without_primary_name(self):
        xml = b"""<items><item id="1"><name type="alternate" value="Alt"/></item></items>"""
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=xml)
            results = search_bgg("test")
        assert results == []

    def test_limits_to_10_results(self):
        items = "".join(
            f'<item id="{i}"><name type="primary" value="Game {i}"/></item>'
            for i in range(15)
        )
        xml = f'<items>{items}</items>'.encode()
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=xml)
            results = search_bgg("game")
        assert len(results) == 10


# ---------------------------------------------------------------------------
# get_bgg_game unit tests
# ---------------------------------------------------------------------------

class TestGetBGGGame:
    def test_returns_correct_dict(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=_BGG_THING_XML)
            result = get_bgg_game(13)
        assert result is not None
        assert result["bgg_id"] == 13
        assert result["name"] == "Catan"
        assert result["year"] == 1995
        assert result["min_players"] == 3
        assert result["max_players"] == 4
        assert result["image_url"] == "https://cf.geekdo-images.com/catan.jpg"
        assert result["source"] == "bgg"
        assert "Trade" in result["description"]

    def test_unescapes_html_entities_in_description(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=_BGG_THING_XML)
            result = get_bgg_game(13)
        assert "&amp;" not in result["description"]
        assert "&" in result["description"]

    def test_handles_202_retry(self):
        first = _mock_response(status_code=202)
        second = _mock_response(content=_BGG_THING_XML)
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.side_effect = [first, second]
            result = get_bgg_game(13)
        assert mock_get.call_count == 2
        assert result is not None
        assert result["name"] == "Catan"

    def test_returns_none_on_double_202(self):
        first = _mock_response(status_code=202)
        second = _mock_response(status_code=202)
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.side_effect = [first, second]
            result = get_bgg_game(13)
        assert mock_get.call_count == 2
        assert result is None

    def test_returns_none_if_no_item(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=_BGG_EMPTY_XML)
            result = get_bgg_game(99999)
        assert result is None

    def test_truncates_description_to_300_chars(self):
        long_desc = "A" * 500
        xml = f'<items><item id="1"><name type="primary" value="Game"/><description>{long_desc}</description></item></items>'.encode()
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(content=xml)
            result = get_bgg_game(1)
        assert len(result["description"]) <= 300


# ---------------------------------------------------------------------------
# search_steam unit tests
# ---------------------------------------------------------------------------

class TestSearchSteam:
    def test_returns_parsed_results(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data=_STEAM_SEARCH_JSON)
            results = search_steam("civilization")
        assert len(results) == 2
        assert results[0]["id"] == "289070"
        assert results[0]["name"] == "Sid Meier's Civilization VI"
        assert results[0]["image"] == "https://cdn.steam/civ6.jpg"
        assert results[0]["source"] == "steam"
        assert results[0]["year"] is None

    def test_returns_empty_on_request_exception(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("timeout")
            with pytest.raises(req.RequestException):
                search_steam("civ")

    def test_handles_missing_tiny_image(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data=_STEAM_SEARCH_JSON)
            results = search_steam("cyberpunk")
        assert results[1]["image"] is None

    def test_limits_to_10_results(self):
        items = [{"id": i, "name": f"Game {i}"} for i in range(15)]
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data={"items": items})
            results = search_steam("game")
        assert len(results) == 10


# ---------------------------------------------------------------------------
# get_steam_game unit tests
# ---------------------------------------------------------------------------

class TestGetSteamGame:
    def test_returns_correct_dict(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data=_STEAM_APPDETAILS_JSON)
            result = get_steam_game(289070)
        assert result is not None
        assert result["steam_app_id"] == 289070
        assert result["name"] == "Sid Meier's Civilization VI"
        assert "civilization" in result["description"].lower()
        assert result["image_url"] == "https://cdn.steam/civ6_header.jpg"
        assert result["source"] == "steam"

    def test_returns_none_when_success_false(self):
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data=_STEAM_APPDETAILS_FAIL_JSON)
            result = get_steam_game(99999)
        assert result is None

    def test_truncates_description_to_300_chars(self):
        data = {
            "1": {
                "success": True,
                "data": {"name": "X", "short_description": "B" * 500, "header_image": ""},
            }
        }
        with patch("game_lookup.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data=data)
            result = get_steam_game(1)
        assert len(result["description"]) <= 300


# ---------------------------------------------------------------------------
# search_games unit tests
# ---------------------------------------------------------------------------

class TestSearchGames:
    def test_bgg_only_calls_search_bgg_not_steam(self):
        with patch("game_lookup.search_bgg") as mock_bgg, \
             patch("game_lookup.search_steam") as mock_steam:
            mock_bgg.return_value = []
            search_games("catan", source="bgg")
        mock_bgg.assert_called_once()
        mock_steam.assert_not_called()

    def test_steam_only_calls_search_steam_not_bgg(self):
        with patch("game_lookup.search_bgg") as mock_bgg, \
             patch("game_lookup.search_steam") as mock_steam:
            mock_steam.return_value = []
            search_games("civ", source="steam")
        mock_steam.assert_called_once()
        mock_bgg.assert_not_called()

    def test_all_calls_both(self):
        with patch("game_lookup.search_bgg") as mock_bgg, \
             patch("game_lookup.search_steam") as mock_steam:
            mock_bgg.return_value = [{"id": "1", "name": "BGG Game", "source": "bgg"}]
            mock_steam.return_value = [{"id": "2", "name": "Steam Game", "source": "steam"}]
            results = search_games("game", source="all")
        assert len(results) == 2
        mock_bgg.assert_called_once()
        mock_steam.assert_called_once()

    def test_returns_empty_for_short_query(self):
        with patch("game_lookup.search_bgg") as mock_bgg, \
             patch("game_lookup.search_steam") as mock_steam:
            assert search_games("a") == []
            assert search_games("") == []
            assert search_games("  ") == []
        mock_bgg.assert_not_called()
        mock_steam.assert_not_called()

    def test_returns_empty_if_api_raises(self):
        with patch("game_lookup.search_bgg") as mock_bgg, \
             patch("game_lookup.search_steam") as mock_steam:
            mock_bgg.side_effect = Exception("network error")
            mock_steam.side_effect = Exception("network error")
            results = search_games("catan", source="all")
        assert results == []


# ---------------------------------------------------------------------------
# /games/search route tests
# ---------------------------------------------------------------------------

def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


class TestGameSearchRoute:
    def test_requires_hx_header(self, client, regular_user):
        _login(client, regular_user.email, "userpass123")
        resp = client.get("/games/search?q=catan")
        assert resp.status_code == 400

    def test_requires_login(self, client):
        resp = client.get(
            "/games/search?q=catan",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_returns_200_with_results(self, client, regular_user):
        _login(client, regular_user.email, "userpass123")
        with patch("routes.public.search_games") as mock_search:
            mock_search.return_value = [
                {"id": "13", "name": "Catan", "year": "1995", "source": "bgg", "image": None}
            ]
            resp = client.get(
                "/games/search?q=catan&source=bgg",
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert b"Catan" in resp.data

    def test_short_query_returns_200_empty(self, client, regular_user):
        _login(client, regular_user.email, "userpass123")
        with patch("routes.public.search_games") as mock_search:
            resp = client.get(
                "/games/search?q=a",
                headers={"HX-Request": "true"},
            )
        mock_search.assert_not_called()
        assert resp.status_code == 200

    def test_api_failure_returns_200_not_500(self, client, regular_user):
        _login(client, regular_user.email, "userpass123")
        with patch("routes.public.search_games") as mock_search:
            mock_search.side_effect = Exception("network error")
            resp = client.get(
                "/games/search?q=catan",
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Suggestion creation with metadata
# ---------------------------------------------------------------------------

@pytest.fixture()
def _published_event_with_registration(app, published_event, regular_user, registration):
    """Reuse conftest fixtures — yields already-committed objects."""
    return published_event, regular_user, registration


class TestSuggestionWithLookup:
    def test_suggest_with_bgg_id_stores_metadata(self, client, app, published_event, regular_user, registration):
        _login(client, regular_user.email, "userpass123")
        details = {
            "bgg_id": 13,
            "name": "Catan (authoritative)",
            "description": "Classic trading game",
            "image_url": "https://example.com/catan.jpg",
            "year": 1995,
            "min_players": 3,
            "max_players": 4,
            "source": "bgg",
        }
        with patch("routes.public.get_bgg_game", return_value=details) as mock_bgg:
            resp = client.post(
                f"/events/{published_event.slug}/suggestions/add",
                data={
                    "game_name": "Catan",
                    "bgg_id": "13",
                    "steam_app_id": "",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        mock_bgg.assert_called_once_with(13)
        with app.app_context():
            suggestion = GameSuggestion.query.filter_by(event_id=published_event.id).first()
            assert suggestion is not None
            assert suggestion.game_name == "Catan (authoritative)"
            assert suggestion.bgg_id == 13
            assert suggestion.game_image_url == "https://example.com/catan.jpg"
            assert suggestion.game_description == "Classic trading game"
            assert suggestion.game_year == 1995
            assert suggestion.game_min_players == 3
            assert suggestion.game_max_players == 4

    def test_suggest_with_steam_id_stores_image(self, client, app, published_event, regular_user, registration):
        _login(client, regular_user.email, "userpass123")
        details = {
            "steam_app_id": 289070,
            "name": "Civilization VI",
            "description": "Turn-based strategy",
            "image_url": "https://cdn.steam/civ6.jpg",
            "year": None,
            "source": "steam",
        }
        with patch("routes.public.get_steam_game", return_value=details) as mock_steam, \
             patch("routes.public.get_bgg_game") as mock_bgg:
            resp = client.post(
                f"/events/{published_event.slug}/suggestions/add",
                data={
                    "game_name": "Civilization VI",
                    "bgg_id": "",
                    "steam_app_id": "289070",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        mock_bgg.assert_not_called()
        mock_steam.assert_called_once_with(289070)
        with app.app_context():
            suggestion = GameSuggestion.query.filter_by(event_id=published_event.id).first()
            assert suggestion.steam_app_id == 289070
            assert suggestion.game_image_url == "https://cdn.steam/civ6.jpg"

    def test_suggest_name_only_no_api_call(self, client, app, published_event, regular_user, registration):
        _login(client, regular_user.email, "userpass123")
        with patch("routes.public.get_bgg_game") as mock_bgg, \
             patch("routes.public.get_steam_game") as mock_steam:
            resp = client.post(
                f"/events/{published_event.slug}/suggestions/add",
                data={"game_name": "Obscure Game", "bgg_id": "", "steam_app_id": ""},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        mock_bgg.assert_not_called()
        mock_steam.assert_not_called()
        with app.app_context():
            suggestion = GameSuggestion.query.filter_by(
                event_id=published_event.id, game_name="Obscure Game"
            ).first()
            assert suggestion is not None
            assert suggestion.game_image_url is None

    def test_suggest_bgg_failure_still_creates(self, client, app, published_event, regular_user, registration):
        _login(client, regular_user.email, "userpass123")
        with patch("routes.public.get_bgg_game", side_effect=Exception("network error")):
            resp = client.post(
                f"/events/{published_event.slug}/suggestions/add",
                data={"game_name": "Catan", "bgg_id": "13", "steam_app_id": ""},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        with app.app_context():
            suggestion = GameSuggestion.query.filter_by(
                event_id=published_event.id, game_name="Catan"
            ).first()
            assert suggestion is not None
            assert suggestion.game_image_url is None


# ---------------------------------------------------------------------------
# Suggestion display tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def rich_suggestion(app, published_event, regular_user, registration):
    s = GameSuggestion(
        event_id=published_event.id,
        suggested_by=regular_user.id,
        game_name="Catan",
        bgg_id=13,
        steam_app_id=None,
        game_image_url="https://example.com/catan.jpg",
        game_description="Classic trading game set on an island.",
        game_year=1995,
        game_min_players=3,
        game_max_players=4,
    )
    _db.session.add(s)
    _db.session.commit()
    return s


@pytest.fixture()
def steam_suggestion(app, published_event, regular_user, registration):
    s = GameSuggestion(
        event_id=published_event.id,
        suggested_by=regular_user.id,
        game_name="Civilization VI",
        bgg_id=None,
        steam_app_id=289070,
        game_image_url="https://cdn.steam/civ6.jpg",
        game_description="Build a civilization to stand the test of time.",
        game_year=None,
        game_min_players=None,
        game_max_players=None,
    )
    _db.session.add(s)
    _db.session.commit()
    return s


# ---------------------------------------------------------------------------
# get_itad_prices unit tests
# ---------------------------------------------------------------------------

class TestGetITADPrices:
    def test_returns_none_when_no_api_key(self):
        with patch("game_lookup.SiteSettings.get", return_value=""):
            result = get_itad_prices(123)
        assert result is None

    def test_returns_none_on_api_error(self, app):
        with app.app_context():
            with patch("game_lookup.SiteSettings.get", return_value="test_key"), \
                 patch("game_lookup.requests.get",
                       side_effect=req.RequestException("timeout")) as mock_req:
                result = get_itad_prices(123)
        assert result is None
        mock_req.assert_called_once()


# ---------------------------------------------------------------------------
# Suggestion display tests
# ---------------------------------------------------------------------------

class TestSuggestionDisplay:
    def test_image_shown_when_set(self, client, published_event, rich_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"https://example.com/catan.jpg" in resp.data

    def test_bgg_link_shown_when_bgg_id_set(self, client, published_event, rich_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"boardgamegeek.com/boardgame/13" in resp.data
        assert b"BGG" in resp.data

    def test_steam_link_shown_when_steam_app_id_set(self, client, published_event, steam_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"store.steampowered.com/app/289070" in resp.data
        assert b"Steam" in resp.data

    def test_player_count_badge_shown(self, client, published_event, rich_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"3" in resp.data and b"4 players" in resp.data

    def test_description_excerpt_shown(self, client, published_event, rich_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"Classic trading game" in resp.data

    def test_itad_link_shown_for_steam_suggestions(self, client, published_event, steam_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"isthereanydeal.com/steam/app/289070" in resp.data

    def test_itad_link_not_shown_for_bgg_suggestions(self, client, published_event, rich_suggestion):
        resp = client.get(f"/events/{published_event.slug}")
        assert resp.status_code == 200
        assert b"isthereanydeal.com" not in resp.data
