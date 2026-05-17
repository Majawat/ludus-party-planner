import html
import logging
import time
import xml.etree.ElementTree as ET

import requests
from flask import current_app

from models import SiteSettings

logger = logging.getLogger(__name__)


def search_bgg(query: str) -> list[dict]:
    """Search BGG for board games matching query.
    Returns up to 10 results: [{id, name, year, source, image}]
    """
    resp = requests.get(
        "https://www.boardgamegeek.com/xmlapi2/search",
        params={"query": query, "type": "boardgame"},
        timeout=10,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    results = []
    for item in root.findall("item")[:10]:
        name_el = item.find("name[@type='primary']")
        year_el = item.find("yearpublished")
        if name_el is not None:
            results.append({
                "id": item.get("id"),
                "name": name_el.get("value"),
                "year": year_el.get("value") if year_el is not None else None,
                "source": "bgg",
                "image": None,
            })
    return results


def get_bgg_game(bgg_id: int | str) -> dict | None:
    """Fetch full details for a BGG game by ID.
    Returns dict with: name, description, image_url, year,
    min_players, max_players, bgg_id.
    BGG may return HTTP 202 (queued) — retries once after 2 seconds.
    """
    url = "https://www.boardgamegeek.com/xmlapi2/thing"
    params = {"id": bgg_id, "stats": 1}

    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code == 202:
        time.sleep(2)
        resp = requests.get(url, params=params, timeout=10)
    if resp.status_code == 202:
        return None  # BGG still processing; caller handles gracefully
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    item = root.find("item")
    if item is None:
        return None

    name_el = item.find("name[@type='primary']")
    desc_el = item.find("description")
    image_el = item.find("thumbnail")
    year_el = item.find("yearpublished")
    minp_el = item.find("minplayers")
    maxp_el = item.find("maxplayers")

    desc = desc_el.text if desc_el is not None else None
    if desc:
        desc = html.unescape(desc)[:300].strip()

    return {
        "bgg_id": int(bgg_id),
        "name": name_el.get("value") if name_el is not None else f"BGG #{bgg_id}",
        "description": desc,
        "image_url": image_el.text if image_el is not None else None,
        "year": int(year_el.get("value")) if year_el is not None else None,
        "min_players": int(minp_el.get("value")) if minp_el is not None else None,
        "max_players": int(maxp_el.get("value")) if maxp_el is not None else None,
        "source": "bgg",
    }


def search_steam(query: str) -> list[dict]:
    """Search Steam store for games matching query.
    Returns up to 10 results: [{id, name, image, source, year}]
    """
    resp = requests.get(
        "https://store.steampowered.com/api/storesearch/",
        params={"term": query, "cc": "US", "l": "english"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("items", [])[:10]:
        results.append({
            "id": str(item["id"]),
            "name": item["name"],
            "image": item.get("tiny_image"),
            "source": "steam",
            "year": None,
        })
    return results


def get_steam_game(app_id: int | str) -> dict | None:
    """Fetch details for a Steam app by ID.
    Returns dict with: name, description, image_url, steam_app_id.
    Returns None when success=False in the API response.
    """
    resp = requests.get(
        "https://store.steampowered.com/api/appdetails",
        params={"appids": app_id, "cc": "US", "l": "english"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    app_data = data.get(str(app_id), {})
    if not app_data.get("success"):
        return None
    g = app_data.get("data", {})
    desc = g.get("short_description", "")[:300] or None
    return {
        "steam_app_id": int(app_id),
        "name": g.get("name", f"Steam #{app_id}"),
        "description": desc,
        "image_url": g.get("header_image"),
        "year": None,
        "source": "steam",
    }


def get_itad_prices(steam_app_id: int | str) -> dict | None:
    """Fetch current price and historical low from ITAD for a Steam game.

    Uses the ITAD API v2.8 (OpenAPI spec confirmed):
      GET /games/lookup/v1?appid={id}  → ITAD UUID
      POST /games/overview/v2          → current deal + historical low

    Returns dict: {current_price, current_currency, lowest_price, lowest_currency,
    lowest_store, itad_url}. Returns None if no key configured or any error. Never raises.
    """
    api_key = SiteSettings.get("itad_api_key", "").strip()
    if not api_key:
        return None
    try:
        lookup_resp = requests.get(
            "https://api.isthereanydeal.com/games/lookup/v1",
            params={"key": api_key, "appid": int(steam_app_id)},
            timeout=10,
        )
        lookup_resp.raise_for_status()
        lookup = lookup_resp.json()
        if not lookup.get("found"):
            return None
        game_id = lookup["game"]["id"]

        ov_resp = requests.post(
            "https://api.isthereanydeal.com/games/overview/v2",
            params={"key": api_key, "country": "US"},
            json=[game_id],
            timeout=10,
        )
        ov_resp.raise_for_status()
        ov_data = ov_resp.json()

        prices_list = ov_data.get("prices", [])
        if not prices_list:
            return None
        entry = prices_list[0]
        current = entry.get("current")
        lowest = entry.get("lowest")
        itad_url = entry.get("urls", {}).get(
            "game", f"https://isthereanydeal.com/steam/app/{steam_app_id}/"
        )
        return {
            "current_price": current["price"]["amount"] if current else None,
            "current_currency": current["price"]["currency"] if current else "USD",
            "lowest_price": lowest["price"]["amount"] if lowest else None,
            "lowest_currency": lowest["price"]["currency"] if lowest else "USD",
            "lowest_store": lowest["shop"]["name"] if lowest else None,
            "itad_url": itad_url,
        }
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        current_app.logger.warning(
            f"ITAD price lookup failed for steam_app_id={steam_app_id}: "
            f"type={type(e).__name__} status={status}"
        )
        return None


def search_games(query: str, source: str = "all") -> list[dict]:
    """Search BGG and/or Steam. source is 'bgg', 'steam', or 'all'.
    Results are interleaved: BGG first then Steam, or filtered.
    Returns [] on any error or query shorter than 2 chars.
    """
    if not query or len(query.strip()) < 2:
        return []
    results = []
    if source in ("bgg", "all"):
        try:
            results.extend(search_bgg(query.strip()))
        except Exception as e:
            logger.warning("game_lookup: bgg search failed: %s", e)
    if source in ("steam", "all"):
        try:
            results.extend(search_steam(query.strip()))
        except Exception as e:
            logger.warning("game_lookup: steam search failed: %s", e)
    return results
