import logging

from django.conf import settings
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from app.models import Item, MediaTypes, Movie, Sources
from app.providers import services, tmdb
from events.models import Event

logger = logging.getLogger(__name__)


def get_items_to_process(user=None):
    """Get items to process for the calendar."""
    # Music tracks never gain a calendar event (a MusicBrainz recording has no
    # progress to schedule), so walking them spent one rate-limited MusicBrainz
    # call each - a 606-second chunk in production - and every dead recording
    # id was re-requested on every reload because a failed fetch is never
    # stamped as checked.
    media_types = [
        choice.value
        for choice in MediaTypes
        if choice
        not in [
            MediaTypes.SEASON,
            MediaTypes.EPISODE,
            MediaTypes.MUSIC,
        ]
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
    # usefully have changed. Only TMDB change-feed hits are exempt: re-checking
    # them is the point. Items picked because they have no events yet follow the
    # window too -- an ended show never gains a season event, and exempting it
    # re-fetched it on every reload (#1158). Never-checked items stay due.
    stale_after_hours = getattr(settings, "CALENDAR_ITEM_STALE_AFTER_HOURS", 0)
    if stale_after_hours > 0:
        fresh_cutoff = now - timezone.timedelta(hours=stale_after_hours)
        change_feed_q = Q(
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            media_id__in=get_changed_tmdb_tv_ids(),
        ) | Q(
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            media_id__in=get_changed_tmdb_movie_ids(),
        )
        selected = selected.exclude(
            Q(calendar_checked_at__gte=fresh_cutoff) & ~change_feed_q,
        )

    return selected.distinct()


def _aired_show_recheck_q():
    """Match annotated shows whose episodes have all aired and are due a look.

    Neither provider announces a new season for a show that is already fully
    aired: TMDB's change feed only covers a few days, and TVDB shows are only
    refreshed while they still have a future episode. Without this, such a show
    never gains the new season's events and sorts into the no-date tail of
    "Next episode air date" (#1531). Needs `has_season_events` and
    `has_future_events` annotated on the queryset.
    """
    recheck_days = getattr(settings, "CALENDAR_AIRED_SHOW_RECHECK_DAYS", 0)
    if recheck_days <= 0:
        return Q(pk__in=[])
    cutoff = timezone.now() - timezone.timedelta(days=recheck_days)
    return Q(has_season_events=True, has_future_events=False) & (
        Q(calendar_checked_at__isnull=True) | Q(calendar_checked_at__lt=cutoff)
    )


def _log_skipped_finished_shows(tv_items, included_ids, limit=40):
    """Name finished shows left out of a reload because they were checked recently.

    A show whose new season never appears is either not selected or selected
    and fetched with nothing new. This line is what tells the two apart in a
    bug report (#1531): a show listed here was skipped, not fetched.
    """
    recheck_days = getattr(settings, "CALENDAR_AIRED_SHOW_RECHECK_DAYS", 0)
    if recheck_days <= 0:
        return
    season_events = Event.objects.filter(
        item__media_id=OuterRef("media_id"),
        item__source=OuterRef("source"),
        item__media_type=MediaTypes.SEASON.value,
    )
    skipped = list(
        tv_items.exclude(id__in=included_ids)
        .annotate(
            has_season_events=Exists(season_events),
            has_future_events=Exists(
                season_events.filter(datetime__gte=timezone.now()),
            ),
        )
        .filter(has_season_events=True, has_future_events=False)
        .order_by("title")
        .values_list("title", "media_id", "calendar_checked_at")[: limit + 1],
    )
    if not skipped:
        return
    logger.info(
        "TV selection: skipped finished shows checked within %d days%s: %s",
        recheck_days,
        f" (first {limit})" if len(skipped) > limit else "",
        "; ".join(
            f"{title} ({media_id}, checked "
            f"{checked_at.date().isoformat() if checked_at else 'never'})"
            for title, media_id, checked_at in skipped[:limit]
        ),
    )


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
            has_future_events=Exists(
                season_events.filter(datetime__gte=timezone.now()),
            ),
            has_undated_events=Exists(
                season_events.filter(
                    item__season_number__gt=0,
                    datetime__year__lt=1900,
                ),
            ),
        )
        .filter(
            Q(media_id__in=changed_tv_ids)
            | Q(has_season_events=False)
            # TMDB can list a season before it has air dates. Those episodes
            # are stored with the year-1 unknown-date sentinel, and TMDB's
            # change feed is capped, so nothing else reliably brings the show
            # back once the dates are published (#1531).
            | Q(has_undated_events=True)
            | _aired_show_recheck_q(),
        )
        .values("id", "media_id", "title", "has_season_events"),
    )

    logger.info(
        "TV selection: %d tracked TMDB shows, %d changed ids, %d selected",
        tracked_count,
        len(changed_tv_ids),
        len(included_tv_rows),
    )
    _log_skipped_finished_shows(tv_items, [row["id"] for row in included_tv_rows])

    for item in included_tv_rows:
        if item["media_id"] in changed_tv_ids:
            logger.info(
                "TV selection: including %s (%s) because TMDB reported changes",
                item["title"],
                item["media_id"],
            )
        elif item["has_season_events"]:
            logger.info(
                "TV selection: including %s (%s) to look for a new season",
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


def _tvdb_ids_with_upcoming_tmdb_events(tv_items):
    """Return TVDB media ids whose verified TMDB counterpart has future episodes.

    A TVDB-preferred user tracks the same show under both identities. TVDB has
    no change feed, so a show whose episodes have all aired waits for the
    weekly recheck even when the TMDB identity already knows that a new season
    started (#1531). The verified ``tvdb_id`` mapping is cached on the TMDB
    Item, so this costs no provider call.
    """
    if getattr(settings, "CALENDAR_AIRED_SHOW_RECHECK_DAYS", 0) <= 0:
        return set()

    tvdb_media_ids = set(tv_items.values_list("media_id", flat=True))
    if not tvdb_media_ids:
        return set()

    tmdb_ids_by_tvdb_id = {}
    for external_ids, media_id in Item.objects.filter(
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        provider_external_ids__has_key="tvdb_id",
    ).values_list("provider_external_ids", "media_id"):
        tvdb_id = (external_ids or {}).get("tvdb_id")
        if tvdb_id:
            tmdb_ids_by_tvdb_id.setdefault(str(tvdb_id), str(media_id))

    tmdb_media_ids = {
        tmdb_ids_by_tvdb_id[tvdb_id]
        for tvdb_id in tvdb_media_ids
        if tvdb_id in tmdb_ids_by_tvdb_id
    }
    if not tmdb_media_ids:
        return set()

    upcoming_tmdb_ids = set(
        Event.objects.filter(
            item__source=Sources.TMDB.value,
            item__media_type=MediaTypes.SEASON.value,
            item__media_id__in=tmdb_media_ids,
            datetime__gte=timezone.now(),
        ).values_list("item__media_id", flat=True),
    )
    return {
        tvdb_id
        for tvdb_id, tmdb_id in tmdb_ids_by_tvdb_id.items()
        if tvdb_id in tvdb_media_ids and tmdb_id in upcoming_tmdb_ids
    }


def get_tvdb_tv_items_to_include(tv_items):
    """Return tracked TVDB TV item ids that should be refreshed.

    TVDB has no change feed equivalent to TMDB's, so refresh shows that have
    no season events yet, plus shows that still have future or unknown-date
    episodes so air dates stay current while a season is ongoing.
    """
    if not tv_items.exists():
        return []

    now = timezone.now()
    counterpart_upcoming_ids = _tvdb_ids_with_upcoming_tmdb_events(tv_items)
    season_events = Event.objects.filter(
        item__media_id=OuterRef("media_id"),
        item__source=OuterRef("source"),
        item__media_type=MediaTypes.SEASON.value,
    )
    # Unknown air dates are stored as datetime.min (year 1); future events
    # include the year-9999 sentinel. Both mean dates may still change.
    # Use year__lt=1900 (not the exact year=1) to match the sentinel: Django's
    # __year= lookup is optimized into a bounds check that converts year-1's
    # lower bound through the DB connection's timezone, which can underflow
    # datetime.MINYEAR and raise OverflowError for negative UTC offsets.
    refreshable_season_events = season_events.filter(
        Q(datetime__gte=now) | Q(datetime__year__lt=1900),
    )

    included_tv_rows = list(
        tv_items.annotate(
            has_season_events=Exists(season_events),
            has_refreshable_events=Exists(refreshable_season_events),
            has_future_events=Exists(
                season_events.filter(datetime__gte=now),
            ),
        )
        .filter(
            Q(has_season_events=False)
            | Q(has_refreshable_events=True)
            | Q(media_id__in=counterpart_upcoming_ids)
            | _aired_show_recheck_q(),
        )
        .values(
            "id", "media_id", "title", "has_season_events", "has_refreshable_events"
        ),
    )

    for item in included_tv_rows:
        if item["has_refreshable_events"]:
            logger.info(
                "TVDB TV selection: including %s (%s) because it has "
                "future or unknown-date episodes",
                item["title"],
                item["media_id"],
            )
        elif item["media_id"] in counterpart_upcoming_ids:
            logger.info(
                "TVDB TV selection: including %s (%s) because its TMDB "
                "counterpart has upcoming episodes",
                item["title"],
                item["media_id"],
            )
        elif item["has_season_events"]:
            logger.info(
                "TVDB TV selection: including %s (%s) to look for a new season",
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

    # Digital and physical dates are stored per user region. A recent movie
    # with none for a tracking user's region gets one fetch per stale window,
    # which also picks up regions set after the movie was first scheduled.
    # Older movies wait for TMDB's change feed.
    region_without_events = Exists(
        Movie.objects.filter(item=OuterRef("pk"))
        .exclude(user__watch_provider_region__in=["", "UNSET"])
        .exclude(
            Exists(
                Event.objects.filter(
                    item=OuterRef("item"),
                    region=OuterRef("user__watch_provider_region"),
                ),
            ),
        ),
    )
    recent_cutoff = timezone.now() - timezone.timedelta(days=365)

    return list(
        set(
            movie_items.filter(
                Q(media_id__in=changed_movie_ids)
                | Q(event__isnull=True)
                | (Q(region_without_events) & Q(event__datetime__gte=recent_cutoff)),
            ).values_list("id", flat=True),
        ),
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
