"""Retro systems, keyed by the platform names IGDB reports.

A game on one of these systems is treated as retro content: ScreenScraper and
Libretro are asked about it, using the system's id in each of them.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class System:
    """One retro system and its identifier in each artwork provider."""

    libretro: str
    screenscraper: int


# IGDB platform names (compared with punctuation and spacing removed) to the
# directory Libretro files its thumbnails under and the ScreenScraper system id.
_SYSTEMS = {
    "Nintendo Entertainment System": System("Nintendo - Nintendo Entertainment System", 3),
    "Super Nintendo Entertainment System": System(
        "Nintendo - Super Nintendo Entertainment System", 4
    ),
    "Game Boy": System("Nintendo - Game Boy", 9),
    "Game Boy Color": System("Nintendo - Game Boy Color", 10),
    "Game Boy Advance": System("Nintendo - Game Boy Advance", 12),
    "Nintendo 64": System("Nintendo - Nintendo 64", 14),
    "Nintendo DS": System("Nintendo - Nintendo DS", 15),
    "Virtual Boy": System("Nintendo - Virtual Boy", 11),
    "Sega Mega Drive/Genesis": System("Sega - Mega Drive - Genesis", 1),
    "Sega Master System/Mark III": System("Sega - Master System - Mark III", 2),
    "Sega Game Gear": System("Sega - Game Gear", 21),
    "Sega CD": System("Sega - Mega-CD - Sega CD", 20),
    "Sega 32X": System("Sega - 32X", 19),
    "Sega Saturn": System("Sega - Saturn", 22),
    "Dreamcast": System("Sega - Dreamcast", 23),
    "PlayStation": System("Sony - PlayStation", 57),
    "Atari 2600": System("Atari - 2600", 26),
    "Atari 5200": System("Atari - 5200", 40),
    "Atari 7800": System("Atari - 7800", 41),
    "Atari Lynx": System("Atari - Lynx", 28),
    "Atari Jaguar": System("Atari - Jaguar", 27),
    "TurboGrafx-16/PC Engine": System("NEC - PC Engine - TurboGrafx 16", 31),
    "PC Engine SuperGrafx": System("NEC - PC Engine SuperGrafx", 105),
    "Neo Geo AES": System("SNK - Neo Geo", 142),
    "Neo Geo MVS": System("SNK - Neo Geo", 142),
    "Neo Geo CD": System("SNK - Neo Geo CD", 70),
    "Neo Geo Pocket": System("SNK - Neo Geo Pocket", 25),
    "Neo Geo Pocket Color": System("SNK - Neo Geo Pocket Color", 82),
    "Arcade": System("MAME", 75),
}


def _key(name):
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


_BY_KEY = {_key(name): system for name, system in _SYSTEMS.items()}


def systems_for(platform_names):
    """Return the distinct retro systems among a game's platform names."""
    found = []
    for name in platform_names or ():
        system = _BY_KEY.get(_key(name))
        if system and system not in found:
            found.append(system)
    return tuple(found)
