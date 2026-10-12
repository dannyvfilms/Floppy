"""Resolve a game's logo and backdrop from the best provider for each.

IGDB stays Floppy's game metadata source and the backdrop fallback. This
package looks for something better first, and the two assets are resolved
independently, so a game can end up with a SteamGridDB logo and a ScreenScraper
backdrop. The result is stored with its provider, so a later "refresh" or "pick
another" does not need a new data model.

Which providers are asked, and in what order, depends on what Floppy knows:

* a Steam AppID: Steam, SteamGridDB, TheGamesDB (and ScreenScraper for retro)
* a retro platform: ScreenScraper, TheGamesDB, SteamGridDB, Libretro
* anything else: SteamGridDB, TheGamesDB

See ``docs/architecture/game-artwork.md``.
"""

import logging
import time
from datetime import timedelta

from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone

from app.game_artwork import (
    libretro,
    screenscraper,
    steam,
    steamgriddb,
    thegamesdb,
)
from app.game_artwork.base import BACKDROP, LOGO, Art, GameQuery
from app.models import GameArtwork, Sources

logger = logging.getLogger(__name__)

# Time budget for one resolution, checked between providers.
RESOLVE_BUDGET_SECONDS = 12
# A game with both assets from a real provider is left alone this long; one with
# a gap is tried again sooner, since a key may have been added since.
COMPLETE_TTL = timedelta(days=30)
INCOMPLETE_TTL = timedelta(hours=6)
# After a provider error nothing is stored; this stops every page view retrying.
ERROR_BACKOFF_SECONDS = 300
IGDB_PROVIDER = "igdb"


def query_for(media_id, metadata):
    """Build the lookup from a game's IGDB metadata (``igdb.game``)."""
    details = metadata.get("details") or {}
    release_date = str(details.get("release_date") or "")
    year = int(release_date[:4]) if release_date[:4].isdigit() else None
    return GameQuery(
        media_id=str(media_id),
        title=metadata.get("title") or "",
        platforms=tuple(details.get("platforms") or ()),
        year=year,
        steam_app_id=(metadata.get("external_ids") or {}).get("steam_app_id", ""),
    )


def provider_order(query):
    """Return the provider modules to ask for this game, best first."""
    if query.steam_app_id:
        order = [steam, steamgriddb, thegamesdb]
        if query.systems:
            order.append(screenscraper)
        return order
    if query.systems:
        return [screenscraper, thegamesdb, steamgriddb, libretro]
    return [steamgriddb, thegamesdb]


def _error_key(media_id):
    return f"game_artwork_error_{media_id}"


def _search(query):
    """Ask providers in order for whichever assets are still missing.

    Returns ``(found, errored)``. One failing provider never stops the others.
    """
    found = {}
    errored = False
    started = time.monotonic()
    for provider in provider_order(query):
        wanted = [kind for kind in (LOGO, BACKDROP) if kind not in found]
        if not wanted:
            break
        if time.monotonic() - started > RESOLVE_BUDGET_SECONDS:
            errored = True
            break
        try:
            found.update(provider.find(query, wanted))
        except Exception:
            errored = True
            logger.warning(
                "Game artwork lookup failed for %s (%s)",
                query.title,
                provider.PROVIDER,
                exc_info=True,
            )
    return found, errored


def is_stale(row):
    """Return whether a stored row is old enough to be looked up again."""
    complete = bool(row.logo_url) and row.backdrop_provider not in ("", IGDB_PROVIDER)
    ttl = COMPLETE_TTL if complete else INCOMPLETE_TTL
    return timezone.now() - row.resolved_at > ttl


def _art(row, kind):
    url = getattr(row, f"{kind}_url")
    if not url:
        return None
    return Art(
        url,
        getattr(row, f"{kind}_provider"),
        getattr(row, f"{kind}_provider_id"),
    )


def resolve(query, *, fallback_backdrop=None):
    """Return ``{"logo": Art | None, "backdrop": Art | None}`` for a game.

    ``fallback_backdrop`` is IGDB's own artwork, used (and recorded as such)
    when no artwork provider has a backdrop.
    """
    row = GameArtwork.objects.filter(
        source=Sources.IGDB.value,
        media_id=query.media_id,
    ).first()
    if row is None or is_stale(row):
        if cache.get(_error_key(query.media_id)):
            found, errored = {}, False
        else:
            found, errored = _search(query)
            if errored and not found:
                cache.set(_error_key(query.media_id), 1, ERROR_BACKOFF_SECONDS)
        if found or not errored:
            row = _store(query, found, fallback_backdrop, existing=row)
    logo = _art(row, LOGO) if row else None
    backdrop = _art(row, BACKDROP) if row else None
    if backdrop is None or backdrop.provider == IGDB_PROVIDER:
        # IGDB's own artwork is read fresh rather than from the stored copy.
        backdrop = fallback_backdrop or backdrop
    return {LOGO: logo, BACKDROP: backdrop}


def _store(query, found, fallback_backdrop, *, existing):
    """Save what was found, keeping an earlier asset a failed search missed."""
    values = {}
    for kind in (LOGO, BACKDROP):
        art = found.get(kind)
        if art is None and kind == BACKDROP:
            art = fallback_backdrop
        if art is None and existing is not None:
            art = _art(existing, kind)
        values[f"{kind}_url"] = art.url if art else ""
        values[f"{kind}_provider"] = art.provider if art else ""
        values[f"{kind}_provider_id"] = art.provider_id if art else ""
    try:
        row, _ = GameArtwork.objects.update_or_create(
            source=Sources.IGDB.value,
            media_id=query.media_id,
            defaults=values,
        )
    except IntegrityError:
        # A concurrent request stored the same game first; theirs is as good.
        row = GameArtwork.objects.get(
            source=Sources.IGDB.value,
            media_id=query.media_id,
        )
    return row
