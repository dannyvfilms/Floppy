import logging

from django.conf import settings
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.providers import services, tmdb
from events.models import Event

logger = logging.getLogger(__name__)


def get_items_to_process(user=None):
    """Get items to process for the calendar."""
    media_types = [
        choice.value
        for choice in MediaTypes
        if choice not in [MediaTypes.SEASON, MediaTypes.EPISODE]
    ]

    query = Q()

    for media_type in media_types:
        media_query = Q(**{f"{media_type}__isnull": False})

        if user:
            media_query &= Q(**{f"{media_type}__user": user})

        query |= media_query

    query &= ~Q(source=Sources.MANUAL.value)

    items = Item.objects.filter(query).distinct()

    return filter_items_to_fetch(items)


def filter_items_to_fetch(items):
    """Filter items that need calendar events according to specific rules."""
    now = timezone.now()
    one_year_ago = now - timezone.timedelta(days=365)

    tv_items = items.filter(
        media_type=MediaTypes.TV.value,
        source=Sources.TMDB.value,
    )
    tv_items_to_include = get_tv_items_to_include(tv_items)

    tvdb_tv_items = items.filter(
        media_type=MediaTypes.TV.value,
        source=Sources.TVDB.value,
    )
    tvdb_tv_items_to_include = get_tvdb_tv_items_to_include(tvdb_tv_items)

    movie_items = items.filter(
        media_type=MediaTypes.MOVIE.value,
        source=Sources.TMDB.value,
    )
    movie_items_to_include = get_movie_items_to_include(movie_items)

    future_events = Event.objects.filter(
        item=OuterRef("pk"),
        datetime__gte=now,
    )

    latest_comic_event = Event.objects.filter(
        item=OuterRef("pk"),
        item__media_type=MediaTypes.COMIC.value,
    ).order_by("-datetime")

    annotated = items.annotate(
        has_future_events=Exists(future_events),
        latest_comic_event_datetime=Subquery(latest_comic_event.values("datetime")[:1]),
    )

    tv_q = Q(id__in=tv_items_to_include) | Q(id__in=tvdb_tv_items_to_include)
    movie_q = Q(id__in=movie_items_to_include)

    comic_q = Q(media_type=MediaTypes.COMIC.value) & (
        Q(event__isnull=True) | Q(latest_comic_event_datetime__gte=one_year_ago)
    )

    other_q = (
        ~Q(media_type__in=[MediaTypes.TV.value, MediaTypes.COMIC.value])
        & ~Q(media_type=MediaTypes.MOVIE.value, source=Sources.TMDB.value)
        & (Q(event__isnull=True) | Q(has_future_events=True))
    )

    selected = annotated.filter(tv_q | movie_q | comic_q | other_q)

    # Provider responses are not cached, so every selected item costs a live
    # network call. Drop the ones checked recently enough that nothing can
    # usefully have changed. Items the TV/movie selectors picked are exempt --
    # those were chosen because TMDB's change feed reported a change, or because
    # they have no events yet, so re-checking them is the point.
    stale_after_hours = getattr(settings, "CALENDAR_ITEM_STALE_AFTER_HOURS", 0)
    if stale_after_hours > 0:
        fresh_cutoff = now - timezone.timedelta(hours=stale_after_hours)
        selected = selected.exclude(
            Q(calendar_checked_at__gte=fresh_cutoff) & ~(tv_q | movie_q),
        )

    return selected.distinct()


def get_tv_items_to_include(tv_items):
    """Return tracked TMDB TV item ids that should be refreshed."""
    tracked_count = tv_items.count()
    if not tracked_count:
        return []

    changed_tv_ids = get_changed_tmdb_tv_ids()
    season_events = Event.objects.filter(
        item__media_id=OuterRef("media_id"),
        item__source=OuterRef("source"),
        item__media_type=MediaTypes.SEASON.value,
    )

    included_tv_rows = list(
        tv_items.annotate(
            has_season_events=Exists(season_events),
        )
        .filter(
            Q(media_id__in=changed_tv_ids) | Q(has_season_events=False),
        )
        .values("id", "media_id", "title", "has_season_events"),
    )

    logger.info(
        "TV selection: %d tracked TMDB shows, %d changed ids, %d selected",
        tracked_count,
        len(changed_tv_ids),
        len(included_tv_rows),
    )

    for item in included_tv_rows:
        if item["media_id"] in changed_tv_ids:
            logger.info(
                "TV selection: including %s (%s) because TMDB reported changes",
                item["title"],
                item["media_id"],
            )
        else:
            logger.info(
                "TV selection: including %s (%s) because it has no season events yet",
                item["title"],
                item["media_id"],
            )

    return [item["id"] for item in included_tv_rows]


def get_tvdb_tv_items_to_include(tv_items):
    """Return tracked TVDB TV item ids that should be refreshed.

    TVDB has no change feed equivalent to TMDB's, so refresh shows that have
    no season events yet, plus shows that still have future or unknown-date
    episodes so air dates stay current while a season is ongoing.
    """
    if not tv_items.exists():
        return []

    now = timezone.now()
    season_events = Event.objects.filter(
        item__media_id=OuterRef("media_id"),
        item__source=OuterRef("source"),
        item__media_type=MediaTypes.SEASON.value,
    )
    # Unknown air dates are stored as datetime.min (year 1); future events
    # include the year-9999 sentinel. Both mean dates may still change.
    refreshable_season_events = season_events.filter(
        Q(datetime__gte=now) | Q(datetime__year=1),
    )

    included_tv_rows = list(
        tv_items.annotate(
            has_season_events=Exists(season_events),
            has_refreshable_events=Exists(refreshable_season_events),
        )
        .filter(
            Q(has_season_events=False) | Q(has_refreshable_events=True),
        )
        .values("id", "media_id", "title", "has_season_events"),
    )

    for item in included_tv_rows:
        if item["has_season_events"]:
            logger.info(
                "TVDB TV selection: including %s (%s) because it has "
                "future or unknown-date episodes",
                item["title"],
                item["media_id"],
            )
        else:
            logger.info(
                "TVDB TV selection: including %s (%s) because it has "
                "no season events yet",
                item["title"],
                item["media_id"],
            )

    return [item["id"] for item in included_tv_rows]


def get_movie_items_to_include(movie_items):
    """Return tracked TMDB movie item ids that should be refreshed."""
    if not movie_items.exists():
        return []

    changed_movie_ids = get_changed_tmdb_movie_ids()

    return list(
        movie_items.filter(
            Q(media_id__in=changed_movie_ids) | Q(event__isnull=True),
        ).values_list("id", flat=True),
    )


def get_changed_tmdb_tv_ids():
    """Return changed TMDB TV ids, tolerating provider errors."""
    try:
        return tmdb.tv_changes()
    except services.ProviderAPIError:
        logger.warning("Failed to fetch TMDB TV changes")
        return set()


def get_changed_tmdb_movie_ids():
    """Return changed TMDB movie ids, tolerating provider errors."""
    try:
        return tmdb.movie_changes()
    except services.ProviderAPIError:
        logger.warning("Failed to fetch TMDB movie changes")
        return set()
