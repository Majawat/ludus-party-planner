import re
import time

import requests

from models import SiteSettings


def _api(method, path, **kwargs):
    """Make an authenticated Challonge API call. Raises requests.RequestException on error."""
    api_key = SiteSettings.get("challonge_api_key", "")
    url = f"https://api.challonge.com/v1{path}.json"
    resp = requests.request(method, url, params={"api_key": api_key}, timeout=10, **kwargs)
    resp.raise_for_status()
    return resp.json()


def create_tournament(name, url_slug, tournament_type, description=""):
    """Create a tournament on Challonge. Returns (challonge_id, full_url)."""
    data = _api("POST", "/tournaments", json={
        "tournament": {
            "name": name,
            "url": url_slug,
            "tournament_type": tournament_type,
            "description": description,
            "open_signup": False,
        }
    })
    t = data["tournament"]
    return t["id"], t["full_challonge_url"]


def add_participants_bulk(url_slug, participants):
    """participants = list of {"name": "..."} dicts. Returns API response."""
    return _api("POST", f"/tournaments/{url_slug}/participants/bulk_add",
                json={"participants": participants})


def remove_participant(url_slug, participant_id):
    _api("DELETE", f"/tournaments/{url_slug}/participants/{participant_id}")


def start_tournament(url_slug):
    return _api("POST", f"/tournaments/{url_slug}/start")


def reset_tournament(url_slug):
    return _api("POST", f"/tournaments/{url_slug}/reset")


def get_tournament(url_slug):
    return _api("GET", f"/tournaments/{url_slug}")


def get_participants(url_slug):
    return _api("GET", f"/tournaments/{url_slug}/participants")


def get_open_matches(url_slug):
    data = _api("GET", f"/tournaments/{url_slug}/matches")
    return [m["match"] for m in data if m["match"]["state"] == "open"]


def report_match(url_slug, match_id, winner_id, scores_csv):
    """scores_csv format: "3-1" or "3-1,2-3,3-2" for multi-game."""
    return _api("PUT", f"/tournaments/{url_slug}/matches/{match_id}",
                json={"match": {"winner_id": winner_id, "scores_csv": scores_csv}})


def delete_tournament(url_slug):
    _api("DELETE", f"/tournaments/{url_slug}")


def generate_url_slug(event_name, tournament_name, username):
    """Generate a Challonge-safe URL slug unique-ified with a timestamp suffix."""
    base = f"{username}-{event_name}-{tournament_name}"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:50]
    return f"{slug}-{int(time.time()) % 10000}"
