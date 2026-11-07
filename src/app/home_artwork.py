"""Shared Home cover-refresh work for the HTML poller and the API transport."""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q


def queue_missing_cover_prefetch(user):
    """Queue album-cover prefetch tasks for any artists/albums missing art."""
    from app.models import AlbumTracker, ArtistTracker
    from app.tasks import prefetch_album_covers_batch

    artist_ids: set[int] = set()
    artist_ids.update(
        ArtistTracker.objects.filter(user=user)
        .filter(Q(artist__image="") | Q(artist__image=settings.IMG_NONE))
        .values_list("artist_id", flat=True)
        .distinct(),
    )
    artist_ids.update(
        AlbumTracker.objects.filter(user=user)
        .filter(Q(album__image="") | Q(album__image=settings.IMG_NONE))
        .exclude(album__artist__isnull=True)
        .values_list("album__artist_id", flat=True)
        .distinct(),
    )
    for artist_id in artist_ids:
        cache_key = f"music:cover-prefetch:{artist_id}"
        if cache.add(cache_key, True, 60 * 10):
            try:
                prefetch_album_covers_batch.delay([artist_id], limit_per_artist=5)
            except Exception:  # pragma: no cover - defensive
                cache.delete(cache_key)


def artwork_cover_fingerprint(user):
    """Cheap fingerprint of the user's missing-cover state.

    The artwork poller only exists to pick up cover-art writes (Artist, Album,
    PodcastShow images), which don't fire user-scoped row-cache invalidation.
    Three indexed counts are enough to detect "a cover arrived since the last
    poll" without rebuilding any rows.
    """
    from app.models import AlbumTracker, ArtistTracker, PodcastShowTracker

    missing_artist = (
        ArtistTracker.objects.filter(user=user)
        .filter(Q(artist__image="") | Q(artist__image=settings.IMG_NONE))
        .count()
    )
    missing_album = (
        AlbumTracker.objects.filter(user=user)
        .filter(Q(album__image="") | Q(album__image=settings.IMG_NONE))
        .count()
    )
    missing_show = (
        PodcastShowTracker.objects.filter(user=user)
        .filter(Q(show__image="") | Q(show__image=settings.IMG_NONE))
        .count()
    )
    return (missing_artist, missing_album, missing_show)


def refresh_home_artwork(user, row_ids, rows_pending):
    """Return the refreshed rows and the row ids that still need cover polling.

    One call refreshes every polled row together. When the missing-cover
    fingerprint is unchanged since the last poll the row rebuild is skipped and
    only the rows that still need covers are returned.
    """
    if not row_ids:
        return [], [], bool(rows_pending)

    cover_state = artwork_cover_fingerprint(user)
    cover_state_key = f"home_artwork_cover_state_{user.id}"
    if cache.get(cover_state_key) == cover_state:
        queue_missing_cover_prefetch(user)
        return [], sorted(row_ids), bool(rows_pending)

    from users.home_screen import build_home_page_groups

    home_groups = build_home_page_groups(
        user,
        items_limit=14,
        only_row_ids=row_ids,
        refresh_row_cache=True,
    )
    rows = [
        row
        for group in home_groups
        for row in group["rows"]
        if row["row_id"] in row_ids
    ]

    if any(row.get("poll_for_covers") for row in rows):
        queue_missing_cover_prefetch(user)

    cache.set(cover_state_key, cover_state, 60 * 60)
    poll_row_ids = sorted(
        row["row_id"] for row in rows if row.get("poll_for_covers")
    )
    return rows, poll_row_ids, bool(rows_pending)
