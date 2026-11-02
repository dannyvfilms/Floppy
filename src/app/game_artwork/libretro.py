"""Libretro thumbnails, a retro safety net with no credentials.

The thumbnail repositories are organised by system and exact game file name
(``Super Mario World (USA).png``). They are not a dependable logo collection,
so this is only a way to keep an obscure retro game from being visually
blank: a logo when ``Named_Logos`` happens to have one, and a title screen or
in-game screenshot as the backdrop.
"""

import re
from urllib.parse import quote

from app.game_artwork.base import BACKDROP, LOGO, Art, image_exists

PROVIDER = "libretro"
BASE_URL = "https://thumbnails.libretro.com"
# Libretro files are named after No-Intro releases, which carry a region.
REGION_SUFFIXES = ("", " (USA)", " (Europe)", " (World)", " (Japan)", " (USA, Europe)")
_UNSAFE = re.compile(r'[&*/:`<>?\\|"]')


def _url(system, folder, name):
    return f"{BASE_URL}/{quote(system.libretro)}/{folder}/{quote(name)}.png"


def find(query, wanted):
    """Return the wanted assets Libretro has for the game on any of its systems."""
    title = _UNSAFE.sub("_", query.title or "").strip()
    if not title:
        return {}
    for system in query.systems:
        for suffix in REGION_SUFFIXES:
            name = f"{title}{suffix}"
            backdrop_url = next(
                (
                    url
                    for url in (
                        _url(system, "Named_Snaps", name),
                        _url(system, "Named_Titles", name),
                    )
                    if image_exists(url)
                ),
                None,
            )
            if not backdrop_url:
                continue
            found = {}
            if BACKDROP in wanted:
                found[BACKDROP] = Art(backdrop_url, PROVIDER, name)
            logo_url = _url(system, "Named_Logos", name)
            if LOGO in wanted and image_exists(logo_url):
                found[LOGO] = Art(logo_url, PROVIDER, name)
            return found
    return {}
