"""Statistics refresh and scheduling — extracted from statistics_cache.py."""

import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Max, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from app import statistics as stats
from app.models import MediaTypes

# Controlled circular: all of these are defined in statistics_cache before the
# re-export block, so they are available on the partial module object when this
# module is first imported (which happens at the bottom of statistics_cache.py).
from app.statistics_cache import (
    PREDEFINED_RANGES,
)
from app.statistics_day_builder import (
    _iter_day_range,
)
from app.statistics_day_cache import (
    _day_cache_key,
    _normalize_day_value,
)

logger = logging.getLogger(__name__)


def _range_day_bounds(start_date, end_date):
    start_day = _normalize_day_value(start_date)
    end_day = _normalize_day_value(end_date)
    if start_day and end_day and start_day > end_day:
        start_day, end_day = end_day, start_day
    return start_day, end_day


def invalidate_all_statistics_days(user_id: int, reason: str | None = None) -> int:
    """Drop every per-day payload for a user and have the next sync rebuild them.

    The published snapshots stay and keep being served until then.
    """
    from app import statistics_sync

    user_model = get_user_model()
    try:
        user = user_model.objects.get(id=user_id)
    except user_model.DoesNotExist:
        return 0

    start_day, end_day = _get_activity_bounds(user)
    day_keys = []
    if start_day is not None and end_day is not None:
        for day in _iter_day_range(start_day, end_day):
            key = _day_cache_key(user_id, day)
            if key:
                day_keys.append(key)

    if day_keys:
        cache.delete_many(day_keys)

    statistics_sync.mark_aggregate(user_id, reason=reason, full_sweep=True)
    logger.info(
        "stats_day_invalidate_all user_id=%s days=%s reason=%s",
        user_id,
        len(day_keys),
        reason or "unspecified",
    )
    return len(day_keys)


def invalidate_statistics_cache(user_id: int, range_name: str | None = None):
    """Mark every range stale while keeping the last published result."""
    from app import statistics_sync

    if range_name and range_name not in PREDEFINED_RANGES:
        return
    statistics_sync.mark_aggregate(user_id, reason=f"range:{range_name or 'all'}")


def _get_predefined_range_dates(range_name: str):
    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    if range_name == "All Time":
        return None, None
    if range_name == "Today":
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()), tz)
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "Yesterday":
        yesterday = today - timedelta(days=1)
        start = timezone.make_aware(
            datetime.combine(yesterday, datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(yesterday, datetime.max.time()), tz)
        return start, end
    if range_name == "This Week":
        monday = today - timedelta(days=today.weekday())
        start = timezone.make_aware(datetime.combine(monday, datetime.min.time()), tz)
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "Last 7 Days":
        start = timezone.make_aware(
            datetime.combine(today - timedelta(days=6), datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "This Month":
        month_start = today.replace(day=1)
        start = timezone.make_aware(
            datetime.combine(month_start, datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "Last 30 Days":
        start = timezone.make_aware(
            datetime.combine(today - timedelta(days=29), datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "Last 90 Days":
        start = timezone.make_aware(
            datetime.combine(today - timedelta(days=89), datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "This Year":
        year_start = today.replace(month=1, day=1)
        start = timezone.make_aware(
            datetime.combine(year_start, datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "Last 6 Months":
        six_months_start = today - relativedelta(months=6)
        if six_months_start.day != today.day:
            six_months_start = (
                six_months_start.replace(day=1) + relativedelta(months=1)
            ) - timedelta(days=1)
        start = timezone.make_aware(
            datetime.combine(six_months_start, datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    if range_name == "Last 12 Months":
        twelve_months_start = today - relativedelta(months=12)
        if twelve_months_start.day != today.day:
            twelve_months_start = (
                twelve_months_start.replace(day=1) + relativedelta(months=1)
            ) - timedelta(days=1)
        start = timezone.make_aware(
            datetime.combine(twelve_months_start, datetime.min.time()), tz
        )
        end = timezone.make_aware(datetime.combine(today, datetime.max.time()), tz)
        return start, end
    return None, None


def _get_activity_bounds(user):
    bounds = []

    def _add_bounds(min_value, max_value):
        if min_value:
            bounds.append(stats._localize_datetime(min_value).date())
        if max_value:
            bounds.append(stats._localize_datetime(max_value).date())

    Episode = apps.get_model("app", "Episode")
    episode_bounds = Episode.all_objects.filter(
        related_season__user=user,
        end_date__isnull=False,
    ).aggregate(min_date=Min("end_date"), max_date=Max("end_date"))
    _add_bounds(episode_bounds.get("min_date"), episode_bounds.get("max_date"))

    Movie = apps.get_model("app", "Movie")
    movie_bounds = Movie.objects.filter(user=user).aggregate(
        min_end=Min("end_date"),
        max_end=Max("end_date"),
        min_start=Min("start_date"),
        max_start=Max("start_date"),
    )
    _add_bounds(movie_bounds.get("min_end"), movie_bounds.get("max_end"))
    _add_bounds(movie_bounds.get("min_start"), movie_bounds.get("max_start"))

    HistoricalMusic = apps.get_model("app", "HistoricalMusic")
    music_bounds = HistoricalMusic.objects.filter(
        Q(history_user=user) | Q(history_user__isnull=True),
        end_date__isnull=False,
    ).aggregate(min_date=Min("end_date"), max_date=Max("end_date"))
    _add_bounds(music_bounds.get("min_date"), music_bounds.get("max_date"))

    HistoricalPodcast = apps.get_model("app", "HistoricalPodcast")
    podcast_bounds = HistoricalPodcast.objects.filter(
        Q(history_user=user) | Q(history_user__isnull=True),
        end_date__isnull=False,
    ).aggregate(min_date=Min("end_date"), max_date=Max("end_date"))
    _add_bounds(podcast_bounds.get("min_date"), podcast_bounds.get("max_date"))

    VideoPlay = apps.get_model("app", "VideoPlay")
    video_bounds = VideoPlay.objects.filter(video__user=user).aggregate(
        min_date=Min("end_date"),
        max_date=Max("end_date"),
    )
    _add_bounds(video_bounds.get("min_date"), video_bounds.get("max_date"))

    for media_type in (
        MediaTypes.ANIME.value,
        MediaTypes.GAME.value,
        MediaTypes.BOARDGAME.value,
        MediaTypes.MANGA.value,
        MediaTypes.BOOK.value,
        MediaTypes.COMIC.value,
    ):
        model = apps.get_model("app", media_type)
        media_bounds = model.objects.filter(user=user).aggregate(
            min_end=Min("end_date"),
            max_end=Max("end_date"),
            min_start=Min("start_date"),
            max_start=Max("start_date"),
        )
        _add_bounds(media_bounds.get("min_end"), media_bounds.get("max_end"))
        _add_bounds(media_bounds.get("min_start"), media_bounds.get("max_start"))

    if not bounds:
        return None, None
    return min(bounds), max(bounds)


def _get_sparse_activity_days(user):
    active_media_types = set(getattr(user, "get_active_media_types", list)())
    if not active_media_types:
        active_media_types = set(MediaTypes.values)

    days = set()
    tz = timezone.get_current_timezone()

    def _add_day(value):
        if not value:
            return
        localized = stats._localize_datetime(value)
        if localized:
            days.add(localized.date())

    def _add_range(start_dt, end_dt):
        if not start_dt or not end_dt:
            return
        start_local = stats._localize_datetime(start_dt)
        end_local = stats._localize_datetime(end_dt)
        if not start_local or not end_local:
            return
        start_day = start_local.date()
        end_day = end_local.date()
        if start_day > end_day:
            start_day, end_day = end_day, start_day
        for offset in range((end_day - start_day).days + 1):
            days.add(start_day + timedelta(days=offset))

    if (
        MediaTypes.TV.value in active_media_types
        or MediaTypes.SEASON.value in active_media_types
    ):
        Episode = apps.get_model("app", "Episode")
        episode_qs = Episode.all_objects.filter(related_season__user=user)
        episode_end_days = (
            episode_qs.filter(
                end_date__isnull=False,
            )
            .annotate(
                day=TruncDate("end_date", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        episode_start_days = (
            episode_qs.filter(
                end_date__isnull=True,
                start_date__isnull=False,
            )
            .annotate(
                day=TruncDate("start_date", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        episode_created_days = (
            episode_qs.filter(
                end_date__isnull=True,
                start_date__isnull=True,
            )
            .annotate(
                day=TruncDate("created_at", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        days.update(day for day in episode_end_days if day)
        days.update(day for day in episode_start_days if day)
        days.update(day for day in episode_created_days if day)

    if MediaTypes.MOVIE.value in active_media_types:
        Movie = apps.get_model("app", "Movie")
        movie_qs = Movie.objects.filter(user=user)
        movie_end_days = (
            movie_qs.filter(
                end_date__isnull=False,
            )
            .annotate(
                day=TruncDate("end_date", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        movie_start_days = (
            movie_qs.filter(
                end_date__isnull=True,
                start_date__isnull=False,
            )
            .annotate(
                day=TruncDate("start_date", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        movie_created_days = (
            movie_qs.filter(
                end_date__isnull=True,
                start_date__isnull=True,
            )
            .annotate(
                day=TruncDate("created_at", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        days.update(day for day in movie_end_days if day)
        days.update(day for day in movie_start_days if day)
        days.update(day for day in movie_created_days if day)

    if MediaTypes.MUSIC.value in active_media_types:
        HistoricalMusic = apps.get_model("app", "HistoricalMusic")
        music_days = (
            HistoricalMusic.objects.filter(
                Q(history_user=user) | Q(history_user__isnull=True),
                end_date__isnull=False,
            )
            .annotate(
                day=TruncDate("end_date", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        days.update(day for day in music_days if day)

    if MediaTypes.PODCAST.value in active_media_types:
        HistoricalPodcast = apps.get_model("app", "HistoricalPodcast")
        podcast_days = (
            HistoricalPodcast.objects.filter(
                Q(history_user=user) | Q(history_user__isnull=True),
                end_date__isnull=False,
            )
            .annotate(
                day=TruncDate("end_date", tzinfo=tz),
            )
            .values_list("day", flat=True)
            .distinct()
        )
        days.update(day for day in podcast_days if day)

    if MediaTypes.VIDEO.value in active_media_types:
        VideoPlay = apps.get_model("app", "VideoPlay")
        video_days = (
            VideoPlay.objects.filter(video__user=user)
            .annotate(day=TruncDate("end_date", tzinfo=tz))
            .values_list("day", flat=True)
            .distinct()
        )
        days.update(day for day in video_days if day)

    for media_type in (
        MediaTypes.ANIME.value,
        MediaTypes.GAME.value,
        MediaTypes.BOARDGAME.value,
        MediaTypes.MANGA.value,
        MediaTypes.BOOK.value,
        MediaTypes.COMIC.value,
    ):
        if media_type not in active_media_types:
            continue
        model = apps.get_model("app", media_type)
        rows = (
            model.objects.filter(user=user)
            .values(
                "start_date",
                "end_date",
                "created_at",
                "progress",
            )
            .iterator(chunk_size=500)
        )
        for row in rows:
            start_dt = row.get("start_date")
            end_dt = row.get("end_date")
            progress = row.get("progress") or 0
            if start_dt and end_dt and progress > 0:
                _add_range(start_dt, end_dt)
                continue
            activity_dt = end_dt or start_dt or row.get("created_at")
            _add_day(activity_dt)

    return sorted(days)


def _resolve_day_list(user, start_date, end_date):
    if start_date and end_date:
        return _iter_day_range(start_date, end_date)
    return _get_sparse_activity_days(user)


def _enqueue_collected_backfills(user_id: int, collector: dict) -> None:
    """Enqueue metadata backfills accumulated across a bulk day rebuild.

    Mirrors the per-day scheduling block in `build_stats_for_day`, but runs
    once with the union of every day's hints instead of once per day.
    """
    if not any(collector.values()):
        return
    try:
        from app.tasks import (
            enqueue_credits_backfill_items,
            enqueue_episode_runtime_backfill,
            enqueue_genre_backfill_items,
            enqueue_runtime_backfill_items,
        )

        if collector["runtime_item_ids"]:
            enqueue_runtime_backfill_items(sorted(collector["runtime_item_ids"]))
        if collector["genre_item_ids"]:
            enqueue_genre_backfill_items(sorted(collector["genre_item_ids"]))
        if collector["episode_runtime_keys"]:
            enqueue_episode_runtime_backfill(sorted(collector["episode_runtime_keys"]))
        if collector["credit_item_ids"]:
            enqueue_credits_backfill_items(
                sorted(collector["credit_item_ids"]), countdown=3
            )
    except Exception as exc:  # pragma: no cover - best-effort scheduling
        logger.debug(
            "stats_backfill_schedule_failed user_id=%s error=%s",
            user_id,
            exc,
        )


def refresh_statistics_cache(user_id: int, range_name: str, chunk_size=None):
    """Rebuild one range synchronously and return its payload.

    Used by the eager/test read path; production rebuilds through the
    background sync (``app.statistics_sync``).
    """
    from app import statistics_sync

    if range_name not in PREDEFINED_RANGES:
        return None
    return statistics_sync.refresh_range_inline(user_id, range_name)


def schedule_statistics_refresh(
    user_id: int,
    range_name: str,
    debounce_seconds: int = 30,
    countdown: int = 3,
    allow_inline: bool = True,
    priority: int | None = None,
    force: bool = False,
):
    """Make sure a background Statistics sync is queued for the user.

    Kept for its many callers. A sync covers every range, so ``range_name``
    only validates the request; ``force`` queues it ahead of other syncs. The
    debounce and countdown arguments are ignored: the sync coalesces itself.
    """
    from app import statistics_sync

    if range_name not in PREDEFINED_RANGES:
        return False
    return statistics_sync.ensure_sync(user_id, urgent=force)


def schedule_all_ranges_refresh(
    user_id: int,
    debounce_seconds: int = 30,
    countdown: int = 3,
    preferred_priority: int | None = None,
    all_time_priority: int | None = None,
):
    """Record that the user's statistics changed, so every range rebuilds.

    Callers that know which days changed should mark them first
    (``invalidate_statistics_days``); this covers the change either way.
    """
    from app import statistics_sync

    statistics_sync.mark_aggregate(user_id, reason="schedule_all_ranges_refresh")
