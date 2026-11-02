"""Steam's own library artwork. Public CDN, no credentials.

Steam publishes a Library Hero (artwork with no text) and a Library Logo (the
logo alone, on transparency) for most games. Newer apps use hashed file names
this path cannot reach, so a miss here is normal and the resolver moves on.
"""

from app.game_artwork.base import BACKDROP, LOGO, Art, image_exists

PROVIDER = "steam"
BASE_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps"
_FILES = {LOGO: "logo.png", BACKDROP: "library_hero.jpg"}


def find(query, wanted):
    """Return the wanted assets Steam serves for the game's AppID."""
    if not query.steam_app_id:
        return {}
    found = {}
    for kind in wanted:
        url = f"{BASE_URL}/{query.steam_app_id}/{_FILES[kind]}"
        if image_exists(url):
            found[kind] = Art(url, PROVIDER, query.steam_app_id)
    return found
