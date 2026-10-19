"""TheGamesDB: a dedicated clear logo and 1080p fanart. Needs an API key."""

from app.game_artwork.base import BACKDROP, LOGO, Art, normalize
from app.providers import credentials, services

PROVIDER = "thegamesdb"
API_URL = "https://api.thegamesdb.net"
_TYPES = {LOGO: "clearlogo", BACKDROP: "fanart"}


def _get(path, params):
    return (services.api_request(PROVIDER, "GET", f"{API_URL}{path}", params=params) or {}).get(
        "data"
    ) or {}


def _game_id(query, api_key):
    """Return the id of the exact-title match, preferring the release year."""
    wanted = normalize(query.title)
    if not wanted:
        return None
    games = _get("/v1.1/Games/ByGameName", {"apikey": api_key, "name": query.title}).get("games") or []
    matches = [game for game in games if normalize(game.get("game_title")) == wanted]
    for game in matches:
        if query.year and str(game.get("release_date") or "").startswith(str(query.year)):
            return game["id"]
    return matches[0]["id"] if matches else None


def find(query, wanted):
    """Return the wanted assets TheGamesDB has for the game."""
    api_key = credentials.get(PROVIDER, "api_key")
    if not api_key:
        return {}
    game_id = _game_id(query, api_key)
    if game_id is None:
        return {}
    data = _get(
        "/v1/Games/Images",
        {
            "apikey": api_key,
            "games_id": game_id,
            "filter[type]": ",".join(_TYPES[kind] for kind in wanted),
        },
    )
    base_url = (data.get("base_url") or {}).get("original")
    images = (data.get("images") or {}).get(str(game_id)) or []
    if not base_url:
        return {}
    found = {}
    for kind in wanted:
        image = next((i for i in images if i.get("type") == _TYPES[kind] and i.get("filename")), None)
        if image:
            found[kind] = Art(f"{base_url}{image['filename']}", PROVIDER, str(image.get("id", "")))
    return found


def gallery(query):
    """Return all fanart available for the matched game."""
    api_key = credentials.get(PROVIDER, "api_key")
    if not api_key:
        return []
    game_id = _game_id(query, api_key)
    if game_id is None:
        return []
    data = _get("/v1/Games/Images", {
        "apikey": api_key, "games_id": game_id, "filter[type]": "fanart",
    })
    base_url = (data.get("base_url") or {}).get("original")
    if not base_url:
        return []
    return [
        {"url": f"{base_url}{image['filename']}"}
        for image in (data.get("images") or {}).get(str(game_id)) or []
        if image.get("type") == "fanart" and image.get("filename")
    ]
