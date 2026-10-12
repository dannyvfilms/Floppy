"""ScreenScraper: retro artwork matched by system and game name.

Floppy identifies itself with developer credentials (``SCREENSCRAPER_DEV_ID``,
``SCREENSCRAPER_DEV_PASSWORD`` and ``SCREENSCRAPER_SOFTNAME``) that come from the
environment and are never committed. Until they exist the provider is inactive.
A member's own ScreenScraper login (``ssid`` and ``sspassword``) is optional and
only raises their personal limits.

ScreenScraper media URLs carry those credentials as query parameters, so the
URL stored and sent to the browser has them removed. ``authenticate`` puts them
back when Floppy's image proxy fetches the image.
"""

from urllib.parse import parse_qsl, urlencode, urlparse

from django.conf import settings

from app.game_artwork.base import BACKDROP, LOGO, Art, normalize
from app.providers import credentials, services

PROVIDER = "screenscraper"
API_URL = "https://api.screenscraper.fr/api2/jeuInfos.php"
HOST = "screenscraper.fr"
_CREDENTIAL_PARAMS = {"devid", "devpassword", "softname", "ssid", "sspassword"}
# Wheel is ScreenScraper's name for a game logo; fanart is its background art.
_MEDIA_TYPES = {LOGO: ("wheel-hd", "wheel"), BACKDROP: ("fanart",)}
# Worldwide first, then the regions most releases are filed under.
_REGION_ORDER = ("wor", "us", "eu", "ss", "jp")


def developer_credentials():
    """Return Floppy's ScreenScraper developer credentials, or None if unset."""
    dev_id = (settings.SCREENSCRAPER_DEV_ID or "").strip()
    dev_password = (settings.SCREENSCRAPER_DEV_PASSWORD or "").strip()
    if not dev_id or not dev_password:
        return None
    return {
        "devid": dev_id,
        "devpassword": dev_password,
        "softname": (settings.SCREENSCRAPER_SOFTNAME or "Floppy").strip(),
    }


def is_screenscraper_url(url):
    """Return whether a URL points at ScreenScraper over HTTPS."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        hostname == HOST or hostname.endswith(f".{HOST}")
    )


def _request_credentials():
    """Developer credentials plus the member's login when they set one."""
    base = developer_credentials()
    if base is None:
        return None
    ssid = credentials.get(PROVIDER, "ssid")
    sspassword = credentials.get(PROVIDER, "sspassword")
    # Each field resolves on its own, so half a personal login could pair with
    # the instance's other half. A login only counts when both come from one tier.
    same_tier = credentials.source_of(PROVIDER, "ssid") == credentials.source_of(
        PROVIDER, "sspassword"
    )
    if ssid and sspassword and same_tier:
        base = {**base, "ssid": ssid, "sspassword": sspassword}
    return base


def strip_credentials(url):
    """Remove credential parameters from a ScreenScraper media URL."""
    parsed = urlparse(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _CREDENTIAL_PARAMS
    ]
    return parsed._replace(query=urlencode(kept, safe="()")).geturl()


def authenticate(url):
    """Return a ScreenScraper media URL with credentials attached, for fetching only."""
    if not is_screenscraper_url(url):
        return url
    auth = _request_credentials()
    if auth is None:
        return url
    parsed = urlparse(url)
    return parsed._replace(
        query=urlencode(
            [*parse_qsl(parsed.query, keep_blank_values=True), *auth.items()],
            safe="()",
        ),
    ).geturl()


def _pick(medias, kind):
    """Return the best media of the wanted kind, by type then region."""
    for media_type in _MEDIA_TYPES[kind]:
        candidates = [m for m in medias if m.get("type") == media_type and m.get("url")]
        if candidates:
            return min(
                candidates,
                key=lambda m: (
                    _REGION_ORDER.index(m["region"]) if m.get("region") in _REGION_ORDER else len(_REGION_ORDER)
                ),
            )
    return None


def find(query, wanted):
    """Return the wanted assets ScreenScraper has for the game on a retro system."""
    auth = _request_credentials()
    if auth is None or not query.systems or not query.title:
        return {}
    for system in query.systems:
        response = services.api_request(
            PROVIDER,
            "GET",
            API_URL,
            params={
                **auth,
                "output": "json",
                "systemeid": system.screenscraper,
                "romnom": query.title,
            },
        )
        game = ((response or {}).get("response") or {}).get("jeu") or {}
        names = [n.get("text") for n in game.get("noms") or []]
        if not game or (names and normalize(query.title) not in {normalize(n) for n in names}):
            continue
        medias = game.get("medias") or []
        found = {}
        for kind in wanted:
            media = _pick(medias, kind)
            if media:
                found[kind] = Art(strip_credentials(media["url"]), PROVIDER, str(game.get("id", "")))
        if found:
            return found
    return {}
