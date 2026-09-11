"""Eligibility check for the media-list SQL pagination fast path (#1004)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.models.choices import MediaTypes
from app.models.manager import SQL_SORTABLE_KEYS

if TYPE_CHECKING:
    from app.media_list_filters import MediaListFilters

# media_type is None => the root /api/v1/media/ endpoint, which merges and
# sorts results across ~15 heterogeneous models — correctly SQL-paginating
# that sort-merge is a separate, materially larger problem than this fast
# path solves. EPISODE uses a bespoke Episode queryset with no dedup/sort
# machinery to hook into. TV/ANIME's "grouped" anime-library entries are the
# union of two separate get_media_list calls plus a per-entry
# next_episode_for_media/annotate_max_progress pass at sort time — not
# something a single SQL LIMIT/OFFSET can correctly express.
_UNSUPPORTED_MEDIA_TYPES = frozenset(
    {
        MediaTypes.EPISODE.value,
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
        # The web route replaces these tracker rows with show/album/artist
        # adapters later in the view, so a generic BasicMedia slice would not
        # describe the visible surface.
        MediaTypes.MUSIC.value,
        MediaTypes.PODCAST.value,
    },
)


def can_paginate_in_sql(
    filters: MediaListFilters | Mapping,
    media_type: str | None,
    sort_filter: str,
) -> bool:
    """Return True if this request's filters+sort admit the SQL fast path.

    False routes the caller to the existing full-materialize-then-Python-
    filter path, unchanged. Keep this conservative: every case listed here
    is a genuine correctness requirement, not a performance guess — see
    app/models/manager.py's SQL_SORTABLE_KEYS/_aggregated_sort_subquery for
    what the fast path can actually express once eligible.
    """
    if isinstance(filters, Mapping):
        # Smart-list rules are already normalized dictionaries.  Keep this
        # adapter here so the eligibility decision has one vocabulary for web
        # query objects and smart rules instead of each surface growing its
        # own subtly different fallback matrix.
        raw_filters = filters
        status_values = filters.get("status") or filters.get("statuses") or ()
        if isinstance(status_values, str):
            status_values = (status_values,)
        filters = _NormalizedFilterView(
            include_no_status=filters.get("include_no_status")
            or any(str(value).lower() == "no_status" for value in status_values),
            rating=filters.get("rating", "all"),
            rating_min=filters.get("rating_min", ""),
            rating_max=filters.get("rating_max", ""),
            collection=filters.get("collection", "all"),
            progress=filters.get("progress", "all"),
            format=filters.get("format", ""),
            author=filters.get("author", ""),
            provider=filters.get("provider", ""),
            pinned_providers=filters.get("pinned_providers") or (),
            origin=filters.get("origin", ""),
            platforms=filters.get("platforms") or filters.get("platform") or (),
        )
        sort_filter = sort_filter or raw_filters.get("sort", "")

    if media_type is None or media_type in _UNSUPPORTED_MEDIA_TYPES:
        return False
    # Statusless entries are a second, unrelated query unioned in after the
    # tracked-entries query — SQL-slicing the tracked query alone would
    # silently drop them from a paginated page.
    if filters.include_no_status:
        return False
    # Rating/collection/progress are only ever evaluated in Python today
    # (collection and rating need a separate correlated query over the
    # *whole* candidate set; progress is TV/ANIME-only, already excluded
    # above defensively).
    if (
        filters.rating != "all"
        or getattr(filters, "rating_min", "")
        or getattr(filters, "rating_max", "")
        or filters.collection != "all"
        or filters.progress != "all"
    ):
        return False
    # provider_region defaults to the sentinel "UNSET" (truthy) and is only
    # meaningful when filters.provider is also set — checking it on its own
    # would force fallback on every request.
    if filters.format or filters.author or filters.provider:
        return False
    if filters.pinned_providers or filters.origin:
        return False
    # Game platforms are SQL-filterable (list_sql_filters); every other
    # media type's platform filtering only happens in Python.
    if filters.platforms and media_type != MediaTypes.GAME.value:
        return False
    sort_key = sort_filter or ""
    # Season rows derive these values from related episodes in the existing
    # Python/season sorter; the generic tracker subquery cannot express that
    # model-specific aggregation safely.
    if media_type == MediaTypes.SEASON.value and sort_key in {
        "start_date",
        "started",
        "end_date",
        "ended",
        "score",
        "progress",
        "plays",
    }:
        return False
    return sort_key in SQL_SORTABLE_KEYS


class _NormalizedFilterView:
    """Small common view over a normalized web or smart-list filter mapping."""

    def __init__(self, **values):
        self.__dict__.update(values)
