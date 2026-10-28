"""Turn a Plex album into a tracked audiobook.

Shared by the Plex history importer and the live Plex webhook so the two can't
drift on how a book is identified, how progress is computed, or what a finished
book looks like. The shape mirrors
``integrations.imports.audiobookshelf.AudiobookshelfImporter._upsert_book``:
a locally-sourced ``book`` Item with ``format="audiobook"``, a synthetic
media_id, and progress measured in minutes.
"""

import hashlib
import logging

from django.conf import settings
from django.utils import timezone

from app.models import Book, Item, MediaTypes, Sources, Status
from app.services.synced_status import keep_held_status
from integrations import plex_cover
from integrations.imports.helpers import stamp_entry_source

logger = logging.getLogger(__name__)

MS_PER_MINUTE = 60 * 1000

# Share of a chapter that must be heard for it to count as played when Plex
# reports an offset but no view count.
_CHAPTER_PLAYED_SHARE = 0.9


def stable_media_id(machine_identifier, album_rating_key):
    """Return a stable synthetic media_id for a Plex album.

    Plex rating keys are only unique within a server, so the machine identifier
    is part of the hash. Same shape as the Audiobookshelf importer's
    ``_stable_media_id``.
    """
    value = f"{machine_identifier}::{album_rating_key}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tag_list(payload, key):
    """Return the tag values under a Plex tag key (Genre, Style, ...)."""
    values = []
    for tag in payload.get(key) or []:
        value = tag.get("tag") if isinstance(tag, dict) else tag
        if value and str(value) not in values:
            values.append(str(value))
    return values


def _release_datetime(album):
    """Return an aware datetime for the album's release year/date, or None."""
    raw = album.get("originallyAvailableAt") or album.get("year")
    if not raw:
        return None
    text = str(raw)
    parsed = None
    if len(text) == 4 and text.isdigit():  # noqa: PLR2004 - "YYYY"
        parsed = timezone.datetime(int(text), 1, 1)
    else:
        try:
            parsed = timezone.datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def track_progress_minutes(tracks):
    """Return (progress_minutes, total_minutes, all_played) for an album.

    A chapter counts as heard when Plex reports a view count, or when its
    resume offset has passed nearly the whole chapter. Anything part-way
    through adds only the offset, so progress tracks where the listener
    actually is.
    """
    listened_ms = 0
    total_ms = 0
    played_count = 0
    counted = 0

    for track in tracks:
        duration = _coerce_int(track.get("duration"))
        offset = _coerce_int(track.get("viewOffset"))
        views = _coerce_int(track.get("viewCount"))
        if duration <= 0:
            continue
        counted += 1
        total_ms += duration

        played = views > 0 or (
            offset > 0 and offset >= duration * _CHAPTER_PLAYED_SHARE
        )
        if played:
            listened_ms += duration
            played_count += 1
        elif offset > 0:
            listened_ms += min(offset, duration)

    all_played = counted > 0 and played_count == counted
    return (
        listened_ms // MS_PER_MINUTE,
        total_ms // MS_PER_MINUTE,
        all_played,
    )


def _last_viewed_at(tracks):
    """Return the most recent listen timestamp across an album's tracks."""
    stamps = [_coerce_int(track.get("lastViewedAt")) for track in tracks]
    latest = max((stamp for stamp in stamps if stamp > 0), default=0)
    if not latest:
        return None
    return timezone.datetime.fromtimestamp(latest, tz=timezone.get_current_timezone())


def build_item_defaults(album, tracks, *, machine_identifier, account_id=None):
    """Return the Item field values describing a Plex album as a book."""
    title = album.get("title") or album.get("parentTitle") or "Unknown Book"
    author = album.get("parentTitle") or album.get("grandparentTitle") or ""
    _, total_minutes, _ = track_progress_minutes(tracks)

    thumb = album.get("thumb") or album.get("parentThumb") or ""
    image = settings.IMG_NONE
    if thumb and account_id:
        image = (
            plex_cover.build_cover_proxy_url(account_id, machine_identifier, thumb)
            or settings.IMG_NONE
        )

    genres = _tag_list(album, "Genre") or _tag_list(album, "Style")

    return {
        "title": title,
        "original_title": title,
        "localized_title": title,
        "image": image,
        "synopsis": album.get("summary") or "",
        "authors": [author] if author else [],
        "genres": genres,
        "runtime_minutes": total_minutes or None,
        "release_datetime": _release_datetime(album),
        "format": "audiobook",
        "metadata_fetched_at": timezone.now(),
    }


def upsert_plex_audiobook(
    user,
    album,
    tracks,
    *,
    machine_identifier,
    account_id=None,
):
    """Create or update the book tracking a Plex audiobook album.

    Returns the Book, or None when the album can't be identified.
    """
    album_rating_key = album.get("ratingKey") or album.get("key")
    if not album_rating_key or not machine_identifier:
        logger.debug("Skipping Plex audiobook without a server-scoped rating key")
        return None

    tracks = tracks or []
    media_id = stable_media_id(machine_identifier, album_rating_key)

    item, _ = Item.objects.update_or_create(
        media_id=media_id,
        source=Sources.PLEX.value,
        media_type=MediaTypes.BOOK.value,
        defaults=build_item_defaults(
            album,
            tracks,
            machine_identifier=machine_identifier,
            account_id=account_id,
        ),
    )

    progress_minutes, total_minutes, all_played = track_progress_minutes(tracks)
    if all_played:
        status = Status.COMPLETED.value
        # Plex can leave a resume offset on a finished chapter; a completed
        # book should read as its full runtime rather than a few minutes short.
        progress_minutes = total_minutes or progress_minutes
    elif progress_minutes > 0:
        status = Status.IN_PROGRESS.value
    else:
        status = Status.PLANNING.value

    listened_at = _last_viewed_at(tracks)
    book, _ = Book.objects.update_or_create(
        user=user,
        item=item,
        defaults=keep_held_status(
            Book.objects.filter(user=user, item=item).first(),
            {
                "progress": progress_minutes,
                "status": status,
                "end_date": listened_at if all_played else None,
            },
            listened_at,
        ),
    )
    return stamp_entry_source(book, "plex")
