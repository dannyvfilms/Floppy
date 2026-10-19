"""SteamGridDB: logos and heroes for modern and older games. Needs an API key."""

from urllib.parse import quote

import requests

from app.game_artwork.base import BACKDROP, LOGO, Art, normalize
from app.providers import credentials, services

PROVIDER = "steamgriddb"
API_URL = "https://www.steamgriddb.com/api/v2"
_ASSETS = {LOGO: "logos", BACKDROP: "heroes"}
# Hero images are wide banners; skip the odd square or portrait upload.
MIN_HERO_RATIO = 1.5


def _get(path, headers, params=None):
    """Return the ``data`` of a SteamGridDB response; a 404 is a clean miss."""
    try:
        response = services.api_request(
            PROVIDER, "GET", f"{API_URL}{path}", params=params, headers=headers
        )
    except requests.exceptions.HTTPError as error:
        if error.response is not None and error.response.status_code == requests.codes.not_found:
            return None
        raise
    return (response or {}).get("data")


def _game_id(query, headers):
    """Find the SteamGridDB game id, preferring the exact Steam AppID."""
    if query.steam_app_id:
        game = _get(f"/games/steam/{query.steam_app_id}", headers)
        if game:
            return game["id"]
    wanted = normalize(query.title)
    if not wanted:
        return None
    for candidate in _get(f"/search/autocomplete/{quote(query.title, safe='')}", headers) or []:
        if normalize(candidate.get("name")) == wanted:
            return candidate["id"]
    return None


def _best(kind, images):
    """Pick the highest scored usable image."""
    usable = [image for image in images if image.get("url")]
    if kind == BACKDROP:
        wide = [
            image
            for image in usable
            if image.get("width") and image.get("height")
            and image["width"] / image["height"] >= MIN_HERO_RATIO
        ]
        usable = wide or usable
    return max(usable, key=lambda image: image.get("score") or 0, default=None)


def find(query, wanted):
    """Return the wanted assets SteamGridDB has for the game."""
    api_key = credentials.get(PROVIDER, "api_key")
    if not api_key:
        return {}
    headers = {"Authorization": f"Bearer {api_key}"}
    game_id = _game_id(query, headers)
    if game_id is None:
        return {}
    found = {}
    for kind in wanted:
        images = _get(
            f"/{_ASSETS[kind]}/game/{game_id}",
            headers,
            params={"nsfw": "false", "humor": "false", "types": "static"},
        )
        best = _best(kind, images or [])
        if best:
            found[kind] = Art(best["url"], PROVIDER, str(best.get("id", "")))
    return found


def gallery(query):
    """Return the game's hero artwork, highest rated first."""
    api_key = credentials.get(PROVIDER, "api_key")
    if not api_key:
        return []
    headers = {"Authorization": f"Bearer {api_key}"}
    game_id = _game_id(query, headers)
    if game_id is None:
        return []
    images = _get(f"/heroes/game/{game_id}", headers, params={
        "nsfw": "false", "humor": "false", "types": "static",
    }) or []
    return [
        {"url": image["url"], "thumb_url": image.get("thumb") or image["url"],
         "width": image.get("width"), "height": image.get("height")}
        for image in sorted(images, key=lambda image: image.get("score") or 0, reverse=True)
        if image.get("url")
    ]
