"""Shared types and helpers for the game artwork providers."""

import re
import unicodedata
from dataclasses import dataclass, field

import requests

from app.game_artwork.systems import System, systems_for

# Per request. The resolver also keeps a total budget across providers.
HTTP_TIMEOUT = (3, 5)

LOGO = "logo"
BACKDROP = "backdrop"


@dataclass(frozen=True, slots=True)
class Art:
    """One resolved image and where it came from."""

    url: str
    provider: str
    provider_id: str = ""


@dataclass(frozen=True, slots=True)
class GameQuery:
    """What the resolver knows about a game, taken from its IGDB metadata."""

    media_id: str
    title: str
    platforms: tuple[str, ...] = ()
    year: int | None = None
    steam_app_id: str = ""
    systems: tuple[System, ...] = field(init=False, default=())

    def __post_init__(self):
        """Derive the retro systems from the platform names."""
        object.__setattr__(self, "systems", systems_for(self.platforms))


def normalize(title):
    """Reduce a title to lowercase letters and digits for exact comparison."""
    decomposed = unicodedata.normalize("NFKD", str(title or ""))
    ascii_title = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_title.lower())


def image_exists(url):
    """Return whether a URL serves an image, probing with HEAD.

    A 404 is a clean "no". Anything else that is not an image response is also
    a "no"; network failures raise so the resolver can tell absence from error.
    """
    response = requests.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    content_type = response.headers.get("Content-Type", "").lower()
    return response.status_code == requests.codes.ok and content_type.startswith(
        "image/",
    )
