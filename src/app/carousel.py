"""Media-details carousel (trailer + photos) resolution.

Distinct from ``backdrops.py``: that module returns a single horizontal image
(or ``None``) for card art, eagerly consulted on hot paths. This module
returns a multi-item {"video", "photos"} payload for the details page's
carousel, fetched lazily (only when the page's carousel fragment is
requested) and only for the media types/sources that actually expose a
trailer or photo gallery.
"""

import logging

from django.core.cache import cache

from app.image_cache import rewrite_image_url
from app.models import GameArtwork, MediaTypes, Sources
from app.providers import services, tmdb

logger = logging.getLogger(__name__)

_TMDB_CAROUSEL_TYPES = (MediaTypes.MOVIE.value, MediaTypes.TV.value, MediaTypes.SEASON.value)


def carousel_supported(media_type, source):
    """Return whether the given media_type/source combination can have a carousel."""
    if source == Sources.TMDB.value and media_type in _TMDB_CAROUSEL_TYPES:
        return True
    return bool(source == Sources.IGDB.value and media_type == MediaTypes.GAME.value)


def confirmed_empty(media_type, source, media_id, *, season_number=None) -> bool:
    """Return True if a prior fetch already confirmed there's no trailer/photos.

    Cache peek only (never fetches), so a page whose carousel was already
    found empty on an earlier view can render the plain, non-carousel layout
    up front instead of paying for the lazy carousel round trip again.
    """
    if source == Sources.TMDB.value and media_type in _TMDB_CAROUSEL_TYPES:
        data = tmdb.peek_carousel_media(media_type, media_id, season_number=season_number)
        if data is None:
            return False
        if media_type == MediaTypes.SEASON.value:
            show_data = tmdb.peek_carousel_media(MediaTypes.TV.value, media_id)
            if show_data is None and not data["video"] and not data["photos"]:
                return False
            has_overview = bool(
                show_data
                and (data.get("backdrop_path") or data["photos"] or show_data.get("backdrop_path") or show_data["photos"])
                and show_data.get("logos")
            )
        else:
            has_overview = bool(
                (data.get("backdrop_path") or data["photos"]) and data.get("logos")
            )
    elif source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        from app.game_artwork import is_stale

        data = cache.get(f"igdb_carousel_v4_{media_id}")
        row = GameArtwork.objects.filter(
            source=Sources.IGDB.value, media_id=str(media_id)
        ).first()
        # No row, or one old enough to be looked up again, means the artwork
        # was never settled (a provider error stores nothing), so the carousel
        # must still load and retry rather than render as empty.
        if row is None or is_stale(row):
            return False
        has_overview = bool(row.logo_url and row.backdrop_url)
    else:
        return False
    return (
        data is not None
        and not data["video"]
        and not data["photos"]
        and not has_overview
    )


def resolve_carousel_media(media_type, source, media_id, *, season_number=None) -> dict | None:
    """Return {"video": {...}|None, "photos": [{"url", "thumb_url"}, ...]} or None."""
    if source == Sources.TMDB.value and media_type in _TMDB_CAROUSEL_TYPES:
        data = tmdb.carousel_media(media_type, media_id, season_number=season_number)
        photos = [
            {
                "url": rewrite_image_url(tmdb.get_carousel_image_url(photo["file_path"], size="w1280")),
                "thumb_url": rewrite_image_url(tmdb.get_carousel_image_url(photo["file_path"], size="w300")),
            }
            for photo in data["photos"]
        ]
        logo_paths = data.get("logos", [])
        backdrop_path = data.get("backdrop_path") or next(
            (photo["file_path"] for photo in data["photos"] if photo.get("file_path")),
            None,
        )
        backdrop_url = None

        if media_type == MediaTypes.SEASON.value:
            show_data = tmdb.carousel_media(MediaTypes.TV.value, media_id)
            logo_paths = show_data.get("logos", [])
            backdrop_path = backdrop_path or show_data.get("backdrop_path") or next(
                (photo["file_path"] for photo in show_data["photos"] if photo.get("file_path")),
                None,
            )
            if not backdrop_path:
                from app.backdrops import resolve_backdrop

                backdrop_url = resolve_backdrop(
                    {
                        "source": source,
                        "media_type": MediaTypes.TV.value,
                        "media_id": media_id,
                    }
                )
        elif not backdrop_path:
            from app.backdrops import resolve_backdrop

            backdrop_url = resolve_backdrop(
                {"source": source, "media_type": media_type, "media_id": media_id}
            )

        overview = None
        if (backdrop_path or backdrop_url) and logo_paths:
            overview = {
                "url": rewrite_image_url(backdrop_url or tmdb.get_carousel_image_url(backdrop_path, size="w1280")),
                "thumb_url": rewrite_image_url(backdrop_url or tmdb.get_carousel_image_url(backdrop_path, size="w300")),
                "logo_url": rewrite_image_url(tmdb.get_carousel_image_url(logo_paths[0], size="w500")),
            }
            removed_overview = False
            remaining_photos = []
            for photo in photos:
                if not removed_overview and photo["url"] == overview["url"]:
                    removed_overview = True
                    continue
                remaining_photos.append(photo)
            photos = remaining_photos

        hero = None
        if backdrop_path or backdrop_url:
            hero = {
                "url": rewrite_image_url(backdrop_url or tmdb.get_carousel_image_url(backdrop_path, size="w1280")),
                "logo_url": overview["logo_url"] if overview else None,
            }
            if not data["video"] and not photos and not overview:
                # A backdrop with no gallery, trailer or logo still earns a
                # one-image carousel (and the phone hero) instead of nothing.
                photos = [
                    {
                        "url": hero["url"],
                        "thumb_url": rewrite_image_url(backdrop_url or tmdb.get_carousel_image_url(backdrop_path, size="w300")),
                    }
                ]

        if not data["video"] and not photos and not overview:
            return None
        return {"video": data["video"], "photos": photos, "overview": overview, "hero": hero}

    if source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        from lists.models import CustomList

        # A visitor is waiting on this fragment: fail fast on a slow or
        # rate-limited provider instead of holding the web worker.
        with services.interactive_request_scope():
            data = CustomList()._get_igdb_carousel_media(media_id)
        photos = [
            {
                # t_screenshot_big_2x and similar named IGDB transforms crop to a
                # fixed canvas; t_1080p only caps resolution, so it keeps the
                # source image's real aspect ratio for the main pane/lightbox.
                "url": rewrite_image_url(_igdb_image_url(image_id)),
                "thumb_url": rewrite_image_url(
                    f"https://images.igdb.com/igdb/image/upload/t_screenshot_big_2x/{image_id}.jpg"
                ),
            }
            for image_id in data["photos"]
        ]
        with services.interactive_request_scope():
            artwork = _game_artwork(media_id, data.get("hero_image_id"))
        backdrop, logo = artwork["backdrop"], artwork["logo"]
        overview = None
        if backdrop and logo:
            overview = {
                "url": rewrite_image_url(backdrop.url),
                "thumb_url": rewrite_image_url(
                    backdrop.url
                    if backdrop.provider != "igdb"
                    else f"https://images.igdb.com/igdb/image/upload/t_screenshot_big_2x/{backdrop.provider_id}.jpg"
                ),
                "logo_url": rewrite_image_url(logo.url),
            }
            removed_overview = False
            remaining_photos = []
            for photo in photos:
                if not removed_overview and photo["url"] == overview["url"]:
                    removed_overview = True
                    continue
                remaining_photos.append(photo)
            photos = remaining_photos
        if not data["video"] and not photos and not overview:
            return None
        hero = None
        if backdrop:
            hero = {
                "url": rewrite_image_url(backdrop.url),
                "logo_url": overview["logo_url"] if overview else None,
            }
        return {"video": data["video"], "photos": photos, "overview": overview, "hero": hero}

    return None


def _igdb_image_url(image_id):
    return f"https://images.igdb.com/igdb/image/upload/t_1080p/{image_id}.jpg"


def _game_artwork(media_id, igdb_hero_image_id):
    """Return the game's logo and backdrop, IGDB artwork being the backdrop fallback."""
    from app.game_artwork import query_for, resolve
    from app.game_artwork.base import Art
    from app.providers import igdb

    fallback = (
        Art(_igdb_image_url(igdb_hero_image_id), "igdb", igdb_hero_image_id)
        if igdb_hero_image_id
        else None
    )
    try:
        return resolve(query_for(media_id, igdb.game(media_id)), fallback_backdrop=fallback)
    except Exception:
        logger.warning("Game artwork lookup failed for game %s", media_id, exc_info=True)
        return {"logo": None, "backdrop": fallback}
