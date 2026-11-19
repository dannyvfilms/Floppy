"""What the artist page and its API send, bounded at any discography size.

The discography is grouped by release type, as before; each group shows its
first ``ARTIST_ALBUM_PAGE_SIZE`` albums and loads the rest a page at a time.
Group sizes and the release count cover every album. Play totals and the
listening date range are SQL aggregates, and play counts and scores are read
only for the albums on screen, so a 600-album artist played many times costs
about what a ten-album one does.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.db import models
from django.db.models.functions import Coalesce

from app.models import Album, AlbumTracker, Music

ARTIST_ALBUM_PAGE_SIZE = 24
_LIST_FIELDS = (
    "id",
    "title",
    "release_date",
    "release_type",
    "image",
    "musicbrainz_release_id",
    "musicbrainz_release_group_id",
)


def artist_albums(user, artist, *, merge=True):
    """Return every album credited to ``artist``, one row per MusicBrainz identity.

    Newest release first. ``merge=False`` picks the canonical row of a
    duplicated identity without merging the rows (the API reads only).
    Rows carry only what grouping, ordering and the cover count read; the
    albums a page shows are loaded in full by ``_full_albums``.
    """
    from app.services.music import canonicalize_albums

    raw_albums = list(
        Album.objects.filter(
            models.Q(artist=artist) | models.Q(artist_credits__artist=artist),
        )
        .only(*_LIST_FIELDS)
        .distinct()
        .order_by("-release_date", "title"),
    )
    albums_by_id = {}
    for album in canonicalize_albums(raw_albums, user=user, merge=merge):
        albums_by_id[album.id] = album
    return list(albums_by_id.values())


def parse_shown(values):
    """Return ``{group label: albums shown}`` from ``"<count>:<label>"`` values."""
    shown = {}
    for value in values or []:
        count, _, label = str(value).partition(":")
        try:
            shown[label] = max(int(count), 0)
        except ValueError:
            continue
    return shown


def discography_page(user, albums, *, shown=None, page_size=ARTIST_ALBUM_PAGE_SIZE):
    """Return the release-type groups with the first page of each.

    Each group carries ``count`` (all its albums), ``albums`` (those shown,
    with play counts and scores), ``shown`` and ``next_offset`` (None once
    the group is complete). ``shown`` keeps a group the viewer already
    expanded at that length when the page redraws.
    """
    from app.services.music import build_discography_groups

    shown = shown or {}
    groups = build_discography_groups(albums)
    visible = []
    for group in groups:
        limit = max(page_size, min(shown.get(group["label"], 0), group["count"]))
        group["albums"] = group["albums"][:limit]
        group["shown"] = len(group["albums"])
        _set_next(group)
        visible.extend(group["albums"])
    full = {album.id: album for album in _full_albums(user, visible)}
    for group in groups:
        group["albums"] = [full[album.id] for album in group["albums"]]
    return groups


def discography_group_slice(
    user,
    albums,
    label,
    *,
    offset=0,
    limit=ARTIST_ALBUM_PAGE_SIZE,
):
    """Return one group's next page, or None when the group does not exist."""
    from app.services.music import build_discography_groups

    for group in build_discography_groups(albums):
        if group["label"] != label:
            continue
        page = _full_albums(user, group["albums"][offset : offset + limit])
        return _set_next(
            {
                "label": label,
                "count": group["count"],
                "albums": page,
                "shown": offset + len(page),
            },
        )
    return None


def _set_next(group):
    """Add where the group's next page starts and the web request that loads it."""
    remaining = group["count"] - group["shown"]
    group["remaining"] = max(remaining, 0)
    group["next_offset"] = group["shown"] if remaining > 0 else None
    group["more_query"] = (
        urlencode({"group": group["label"], "offset": group["shown"]})
        if remaining > 0
        else ""
    )
    return group


def _full_albums(user, albums):
    """Return ``albums`` reloaded in full, in order, with plays and score.

    A fixed handful of queries for the albums given, whatever their play
    history.
    """
    if not albums:
        return []
    album_ids = [album.id for album in albums]
    by_id = (
        Album.objects.select_related("artist")
        .prefetch_related(
            "artist_credits__artist",
        )
        .in_bulk(album_ids)
    )
    albums = [by_id[album_id] for album_id in album_ids if album_id in by_id]
    plays = album_play_counts(user, album_ids)
    scores = dict(
        AlbumTracker.objects.filter(
            user=user,
            album_id__in=album_ids,
            score__isnull=False,
        ).values_list("album_id", "score"),
    )
    for album in albums:
        album.play_count = plays.get(album.id, 0)
        album.score = scores.get(album.id)
    return albums


def album_play_counts(user, album_ids):
    """Return ``{album_id: plays}`` for the viewer, in one grouped query."""
    if not album_ids:
        return {}
    entry_album = Music.objects.filter(pk=models.OuterRef("id")).values("album_id")[:1]
    rows = (
        Music.history.model.objects.filter(
            id__in=Music.objects.filter(
                user=user,
                album_id__in=album_ids,
            ).values("id"),
        )
        .order_by()
        .annotate(entry_album=models.Subquery(entry_album))
        .values("entry_album")
        .annotate(plays=models.Count("history_id"))
        .values_list("entry_album", "plays")
    )
    return dict(rows)


def artist_music_entries(user, artist):
    """Return the viewer's Music entries on albums credited to ``artist``."""
    return Music.objects.filter(
        models.Q(album__artist=artist) | models.Q(album__artist_credits__artist=artist),
        user=user,
    )


def artist_play_totals(user, artist):
    """Return ``(total_plays, first, last, collapse_same_day)`` in two queries.

    Each entry counts once even when its album credits the artist twice.
    First is the earliest start (else end), last the latest end (else
    start), as ``music_views._music_activity_date_range`` reads them.
    """
    entry_ids = artist_music_entries(user, artist).values("id")
    total_plays = Music.history.model.objects.filter(id__in=entry_ids).count()
    dates = Music.objects.filter(id__in=entry_ids).aggregate(
        first=models.Min(Coalesce("start_date", "end_date")),
        last=models.Max(Coalesce("end_date", "start_date")),
    )
    first_date, last_date = dates["first"], dates["last"]
    collapse_same_day = bool(
        first_date and last_date and first_date.date() == last_date.date(),
    )
    return total_plays, first_date, last_date, collapse_same_day
