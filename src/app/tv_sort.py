"""TV "time left" order.

The order is defined once, over ``TimeLeftRecord``: the few numbers ranking
reads for one show. Two producers build that record:

- ``_record_from_media`` reads a hydrated tracker (seasons, plays and their
  items prefetched). It is what ``_sort_tv_media_by_time_left`` does for a
  list of trackers.
- ``build_time_left_records`` reads ``app.tv_show_facts`` for trackers that
  carry only their item. The TV list uses it, so ranking a library does not
  load a model per season, play and episode.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

from app import helpers
from app.models import BasicMedia, Item, MediaTypes, Status
from app.models.episode_runtimes import (
    EXCLUDED_RUNTIME_SENTINELS,
    build_season_runtime_index,
    default_runtime_minutes,
)
from app.tv_show_facts import SeasonFacts, ShowFacts, tv_show_facts

logger = logging.getLogger(__name__)

RUNTIME_UNKNOWN_AIRED = 999998  # aired but runtime unknown

_ACTIVE_STATUSES = frozenset(
    {
        Status.IN_PROGRESS.value,
        Status.PLANNING.value,
        Status.PAUSED.value,
    },
)


def _has_local_runtime(item):
    """Return whether the item carries a real runtime rather than a marker."""
    runtime_minutes = getattr(item, "runtime_minutes", None)
    return bool(runtime_minutes) and runtime_minutes < RUNTIME_UNKNOWN_AIRED


@dataclass(slots=True)
class TimeLeftRecord:
    """What the time-left order reads for one show, and what it answers."""

    # The show's item.
    title: str
    media_id: str
    source: str
    runtime_minutes: int | None
    # The tracker. ``progress`` is None for an entry nothing tracks.
    status: str | None
    progress: int | None
    # Released episodes outside dropped seasons, and the count per season
    # (``annotate_max_progress``). ``has_max_progress`` is False for a tracker
    # that was never annotated.
    max_progress: int | None
    breakdown: dict
    has_max_progress: bool = True
    # None for a tracker that has no seasons relation at all.
    seasons: list[SeasonFacts] | None = field(default_factory=list)
    # Newest activity, for the caught-up and completed groups.
    end_date: datetime | None = None
    # What the order is cached as.
    media_pk: int | None = None
    item_pk: int | None = None
    # The object the record was read from, when there is one.
    entry: object = None
    # Answers.
    time_left_display: str | None = None
    episodes_left_display: int = 0
    effective_max: int | None = None

    @property
    def show_key(self):
        """Return the identity episode runtimes are stored under."""
        return (self.media_id, self.source)


def _record_from_media(media):
    """Build the record for a hydrated tracker or list entry."""
    item = media.item
    progress = media.progress if hasattr(media, "max_progress") else None
    seasons = None
    if progress is not None and getattr(media, "seasons", None) is not None:
        seasons = []
        for season in media.seasons.all():
            season_number = getattr(season.item, "season_number", 0)
            counted = bool(season_number) and season.status != Status.DROPPED.value
            seasons.append(
                SeasonFacts(
                    season_number=season_number,
                    status=season.status,
                    progress=season.progress if counted else 0,
                    max_episode_number=max(
                        (
                            getattr(episode.item, "episode_number", 0) or 0
                            for episode in season.episodes.all()
                        ),
                        default=0,
                    )
                    if season_number and hasattr(season, "episodes")
                    else 0,
                ),
            )
    return TimeLeftRecord(
        title=item.title,
        media_id=item.media_id,
        source=item.source,
        runtime_minutes=getattr(item, "runtime_minutes", None),
        status=getattr(media, "status", Status.IN_PROGRESS.value),
        progress=progress,
        max_progress=getattr(media, "max_progress", None),
        has_max_progress=hasattr(media, "max_progress"),
        breakdown=getattr(media, "released_episode_breakdown", {}) or {},
        seasons=seasons,
        end_date=(
            getattr(media, "aggregated_end_date", None)
            or getattr(media, "end_date", None)
            or getattr(media, "progressed_at", None)
            or getattr(media, "created_at", None)
        ),
        entry=media,
    )


def build_time_left_records(user, entries, now=None):
    """Return one record per list entry, read from grouped facts.

    ``entries`` are list entries whose ``media`` is a TV tracker carrying its
    item and nothing else (``get_media_list(prefetch_graph=False)``), or None
    for an item nothing tracks. Costs a fixed number of queries; no season,
    play or episode model is built.
    """
    tracked = [entry.media for entry in entries if entry.media is not None]
    facts = tv_show_facts(user, [media.pk for media in tracked])
    breakdowns = (
        BasicMedia.objects.released_episode_breakdowns(
            {(media.item.media_id, media.item.source) for media in tracked},
            now,
        )
        if tracked
        else {}
    )

    records = []
    for entry in entries:
        media = entry.media
        item = entry.item
        if media is None:
            records.append(
                TimeLeftRecord(
                    title=item.title,
                    media_id=item.media_id,
                    source=item.source,
                    runtime_minutes=item.runtime_minutes,
                    status=None,
                    progress=None,
                    max_progress=None,
                    breakdown={},
                    item_pk=item.pk,
                ),
            )
            continue
        show = facts.get(media.pk) or ShowFacts()
        breakdown = breakdowns.get((item.media_id, item.source), {})
        end_date = show.end_date
        records.append(
            TimeLeftRecord(
                title=item.title,
                media_id=item.media_id,
                source=item.source,
                runtime_minutes=item.runtime_minutes,
                status=media.status,
                progress=show.progress,
                max_progress=BasicMedia.objects.released_max_progress(
                    item,
                    breakdown,
                    show.dropped_season_numbers if breakdown else (),
                ),
                breakdown=breakdown,
                seasons=show.seasons,
                # A show's end date and its last progress are the same play.
                end_date=end_date or media.created_at,
                media_pk=media.pk,
                item_pk=media.item_id,
            ),
        )
    return records


def is_caught_up_record(record, item):
    """Answer ``helpers.is_caught_up_media`` for a record instead of a tracker."""
    return helpers.is_caught_up_media(
        SimpleNamespace(
            item=item,
            max_progress=record.max_progress,
            progress=record.progress,
            released_episode_breakdown=record.breakdown,
            seasons=SimpleNamespace(all=lambda: record.seasons or ()),
        ),
    )


def _effective_max_progress(record):
    """Prefer annotated max_progress; fall back to tracked plays to avoid negatives."""
    annotated = record.max_progress or 0
    if annotated <= 0 or annotated < record.progress:
        total_from_plays = sum(
            season.max_episode_number
            for season in record.seasons or ()
            if season.season_number
        )
        return max(annotated, total_from_plays)
    return annotated


def _time_left_sort_context(record, effective_max):
    """Return (episodes_left, progress, breakdown) with dropped seasons left out."""
    base = (
        max(effective_max - record.progress, 0),
        record.progress,
        record.breakdown,
    )
    if record.status == Status.DROPPED.value:
        return base

    seasons = [season for season in record.seasons or () if season.season_number]
    if not seasons or not record.breakdown:
        return base

    dropped_season_numbers = {
        season.season_number
        for season in seasons
        if season.status == Status.DROPPED.value
    }
    if not dropped_season_numbers:
        return base

    filtered_breakdown = {
        season_num: count
        for season_num, count in record.breakdown.items()
        if season_num not in dropped_season_numbers
    }
    if filtered_breakdown == record.breakdown:
        return base

    included_progress = sum(
        season.progress for season in seasons if season.status != Status.DROPPED.value
    )
    return (
        max(sum(filtered_breakdown.values()) - included_progress, 0),
        included_progress,
        filtered_breakdown,
    )


def _episode_runtime_index(show_keys):
    """Return ``{show_key: {season_number: {episode_number: runtime}}}``."""
    index = {}
    if not show_keys:
        return index
    rows = (
        Item.objects.filter(
            media_type=MediaTypes.EPISODE.value,
            media_id__in={media_id for media_id, _ in show_keys},
            source__in={source for _, source in show_keys},
            runtime_minutes__isnull=False,
        )
        .exclude(runtime_minutes__in=EXCLUDED_RUNTIME_SENTINELS)
        .values_list(
            "media_id",
            "source",
            "season_number",
            "episode_number",
            "runtime_minutes",
        )
    )
    for media_id, source, season_number, episode_number, runtime in rows:
        index.setdefault((media_id, source), {}).setdefault(season_number, {})[
            episode_number
        ] = runtime
    return index


class _RuntimeTotals:
    """Minutes left for the shows that have episodes left.

    Episode runtimes and cached season metadata are read once, for those
    shows only, before any total is asked for. Reading season metadata inside
    the sort instead cost up to five cache round trips per show (#725).
    """

    def __init__(self, records):
        self._episodes = _episode_runtime_index({record.show_key for record in records})
        # Only shows with no stored runtime and no episode runtimes reach the
        # season metadata, so this is usually a small part of the library.
        self._season_average = build_season_runtime_index(
            record.media_id
            for record in records
            if not _has_local_runtime(record)
            and not self._episodes.get(record.show_key)
        )

    def _unwatched_runtime_total(self, record, breakdown, progress):
        """Sum actual runtimes of unwatched episodes: (total, episodes counted)."""
        if not breakdown:
            return None, 0

        total_runtime = 0
        episodes_with_runtime_data = 0
        remaining_progress = progress
        show_runtimes = self._episodes.get(record.show_key, {})

        # Seasons in order decide which episodes are unwatched.
        for season_num in sorted(breakdown.keys()):
            season_episode_count = breakdown[season_num]
            if remaining_progress >= season_episode_count:
                remaining_progress -= season_episode_count
                continue
            watched_in_season = remaining_progress
            remaining_progress = 0
            runtimes = [
                runtime
                for episode_number, runtime in show_runtimes.get(season_num, {}).items()
                if episode_number > watched_in_season
            ]
            if runtimes:
                total_runtime += sum(runtimes)
                episodes_with_runtime_data += len(runtimes)

        if episodes_with_runtime_data > 0:
            return total_runtime, episodes_with_runtime_data
        return None, 0

    def _average_runtime_minutes(self, record):
        """Best-effort average episode runtime for a show (fallback only)."""
        # Stored runtime first, unless it is one of the "unknown" markers.
        runtime_minutes = record.runtime_minutes if _has_local_runtime(record) else None

        if not runtime_minutes:
            all_runtimes = [
                runtime
                for season_runtimes in self._episodes.get(record.show_key, {}).values()
                for runtime in season_runtimes.values()
            ]
            if all_runtimes:
                runtime_minutes = round(sum(all_runtimes) / len(all_runtimes))

        if not runtime_minutes:
            runtime_minutes = self._season_average.get(record.media_id)

        if not runtime_minutes or runtime_minutes <= 0:
            runtime_minutes = default_runtime_minutes(record.source)
        return runtime_minutes

    def minutes_left(self, record, episodes_left, breakdown, progress):
        """Return total minutes left: exact where runtimes are known, else estimated."""
        total_runtime, episodes_with_data = self._unwatched_runtime_total(
            record,
            breakdown,
            progress,
        )
        if total_runtime is not None and episodes_with_data == episodes_left:
            return total_runtime
        if total_runtime is not None and episodes_with_data > 0:
            # Partial data: what is known plus an estimate for the rest.
            missing_episodes = episodes_left - episodes_with_data
            average_runtime = total_runtime / episodes_with_data
            return total_runtime + int(missing_episodes * average_runtime)
        runtime = self._average_runtime_minutes(record)
        if not runtime or runtime <= 0:
            runtime = 30
        return episodes_left * runtime


def _minutes_display(total):
    hours = int(total // 60)
    minutes = int(total % 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _newest_first_key(record):
    return (
        -(record.end_date.timestamp() if record.end_date else float("-inf")),
        record.title.lower(),
    )


def sort_time_left_records(records, direction="asc"):
    """Order records by time left and fill in their display values.

    Group order:
      1) Active (episodes left, not dropped) by least total time left first
      2) In progress and caught up, newest activity first
      3) Completed with nothing left, newest activity first
      4) Dropped, by least time left first
      5) Everything else (nothing released, unknown, untracked), input order

    ``desc`` is the exact reverse of that list.
    """
    group_active = []
    group_inprog_zero = []
    group_completed = []
    group_dropped = []
    group_tail = []

    for record in records:
        if not record.has_max_progress or record.progress is None:
            group_tail.append(record)
            continue

        # Keep sorting fast by relying on scheduled calendar refreshes.
        effective_max = max(
            record.max_progress or 0,
            _effective_max_progress(record) or 0,
            record.progress,
        )
        record.effective_max = effective_max
        context = _time_left_sort_context(record, effective_max)
        episodes_left = context[0]
        status = record.status

        if status == Status.DROPPED.value:
            group_dropped.append(record)
        elif episodes_left == 0 and status == Status.IN_PROGRESS.value:
            group_inprog_zero.append(record)
        elif episodes_left == 0 and status == Status.COMPLETED.value:
            group_completed.append(record)
        elif episodes_left > 0 and status in _ACTIVE_STATUSES:
            group_active.append((record, context))
        else:
            group_tail.append(record)

    # Dropped shows count what is left against the whole show.
    dropped_left = {}
    for record in group_dropped:
        if record.effective_max > 0:
            dropped_left[id(record)] = max(record.effective_max - record.progress, 0)

    runtime_totals = _RuntimeTotals(
        [record for record, _ in group_active]
        + [record for record in group_dropped if dropped_left.get(id(record))],
    )

    # 1) Active by least total minutes left
    active_keys = {}
    for record, (episodes_left, progress, breakdown) in group_active:
        total = runtime_totals.minutes_left(record, episodes_left, breakdown, progress)
        record.episodes_left_display = episodes_left
        record.time_left_display = (
            _minutes_display(total) if total > 0 else f"{episodes_left} ep"
        )
        active_keys[id(record)] = (total, record.title.lower())
    group_active_sorted = sorted(
        (record for record, _ in group_active),
        key=lambda record: active_keys[id(record)],
    )

    # 2) and 3) caught up, newest activity first
    for record in group_inprog_zero + group_completed:
        record.episodes_left_display = 0
        record.time_left_display = "0m"
    group_inprog_zero_sorted = sorted(group_inprog_zero, key=_newest_first_key)
    group_completed_sorted = sorted(group_completed, key=_newest_first_key)

    # 4) Dropped: remaining content, least time left first
    dropped_keys = {}
    for record in group_dropped:
        total = 0
        if id(record) in dropped_left:
            episodes_left = dropped_left[id(record)]
            record.episodes_left_display = episodes_left
            if episodes_left > 0:
                total = runtime_totals.minutes_left(
                    record,
                    episodes_left,
                    record.breakdown,
                    record.progress,
                )
                record.time_left_display = _minutes_display(total)
            else:
                record.time_left_display = "0m"
        else:
            # Nothing known to be released.
            record.episodes_left_display = 0
            record.time_left_display = "-"
        dropped_keys[id(record)] = (total, record.title.lower())
    group_dropped_sorted = sorted(
        group_dropped,
        key=lambda record: dropped_keys[id(record)],
    )

    # 5) Tail (unreleased/unknown)
    for record in group_tail:
        record.episodes_left_display = 0
        record.time_left_display = "-"

    sorted_records = (
        group_active_sorted
        + group_inprog_zero_sorted
        + group_completed_sorted
        + group_dropped_sorted
        + group_tail
    )
    logger.debug(
        "time_left groups -> active: %d, caught up: %d, completed: %d, "
        "dropped: %d, tail: %d",
        len(group_active_sorted),
        len(group_inprog_zero_sorted),
        len(group_completed_sorted),
        len(group_dropped_sorted),
        len(group_tail),
    )

    if direction == "desc":
        sorted_records.reverse()
    return sorted_records


def _sort_tv_media_by_time_left(media_list, direction="asc"):
    """Sort TV media by time left; see ``sort_time_left_records`` for the order.

    Accepts hydrated trackers or list entries, which are returned in order
    with ``time_left_display``, ``episodes_left_display`` and the effective
    ``max_progress`` set on them, or ``TimeLeftRecord`` objects, which are
    returned as they are.
    """
    records = [
        media if isinstance(media, TimeLeftRecord) else _record_from_media(media)
        for media in media_list
    ]
    sorted_media = []
    for record in sort_time_left_records(records, direction):
        media = record.entry
        if media is None:
            sorted_media.append(record)
            continue
        if record.effective_max is not None:
            media.max_progress = record.effective_max
        media.episodes_left_display = record.episodes_left_display
        media.time_left_display = record.time_left_display
        sorted_media.append(media)
    return sorted_media
