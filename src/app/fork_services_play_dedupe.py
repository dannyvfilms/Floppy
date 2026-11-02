# FORK: shared duplicate-play detection used by the Trakt and Plex importers
# and by the webhook handlers. Before this module each of those carried its own
# copy of the same nearest-neighbour check with a different window and a
# different idea of where plays are stored, so whether a Trakt play and its
# Plex counterpart survived as two rows depended on which one was imported
# first. See issue #642.
import logging
from bisect import bisect_left, insort
from datetime import timedelta, timezone

import app.models

logger = logging.getLogger(__name__)


class _PlainSortedList(list):
    """Slower stand-in for sortedcontainers.SortedList, with the calls used here."""

    def add(self, value):
        """Insert value, keeping the list sorted."""
        insort(self, value)

    def bisect_left(self, value):
        """Return the leftmost index where value could be inserted."""
        return bisect_left(self, value)


try:
    from sortedcontainers import SortedList
except ModuleNotFoundError:
    # A source install whose environment missed `uv sync` after an update (#1522)
    # would otherwise fail to boot over a speed-up. Same answers, slower inserts.
    logger.warning(
        "sortedcontainers is not installed; using a slower fallback. "
        "Run `uv sync --locked --no-default-groups` in the environment Floppy runs from.",
    )
    SortedList = _PlainSortedList

# Fallback window used when the item's runtime is unknown. Matches the flat
# window the Plex importer used before this module existed.
DEFAULT_DUPLICATE_PLAY_WINDOW = timedelta(hours=3)
MIN_DUPLICATE_PLAY_WINDOW = timedelta(minutes=15)
MAX_DUPLICATE_PLAY_WINDOW = timedelta(hours=3)


def duplicate_play_window(runtime_minutes=None):
    """Return the window in which two plays of one item count as the same play.

    The skew between two sources describing one viewing scales with the item's
    runtime: a Plex webhook fires at ~90% progress while Trakt's scrobbler
    waits for playback to stop, and a pause stretches the gap further. Sizing
    the window by runtime also keeps a genuine back-to-back rewatch, because a
    second play cannot finish sooner than one runtime after the first.
    """
    if not runtime_minutes:
        return DEFAULT_DUPLICATE_PLAY_WINDOW

    window = timedelta(minutes=runtime_minutes)
    return min(max(window, MIN_DUPLICATE_PLAY_WINDOW), MAX_DUPLICATE_PLAY_WINDOW)


class PlayTimes:
    """Known play timestamps for a set of items, keyed however the caller likes.

    Holds the runtime alongside the timestamps so the window is sized per item
    rather than per call site.
    """

    def __init__(self):
        """Start with no known plays."""
        self._times = {}
        self._index = {}
        self._runtimes = {}

    def record_runtime(self, key, runtime_minutes):
        """Remember an item's runtime, ignoring a later unknown value."""
        if runtime_minutes and not self._runtimes.get(key):
            self._runtimes[key] = runtime_minutes

    def add(self, key, played_at, runtime_minutes=None):
        """Record a play so later candidates are measured against it too."""
        self.record_runtime(key, runtime_minutes)
        if played_at is None:
            return
        self._times.setdefault(key, []).append(played_at)
        if key not in self._index:
            self._index[key] = SortedList()
        timestamps = self._index[key]
        # Python compares two datetimes sharing a DST timezone by wall time,
        # but compares different timezones by UTC. Such mixed orderings are
        # not a total temporal order. Keep the original scan for those inputs
        # (and mixed naive/aware histories), including its exception behavior.
        if (
            played_at.tzinfo is not None and not isinstance(played_at.tzinfo, timezone)
        ) or (
            timestamps and (timestamps[0].tzinfo is None) != (played_at.tzinfo is None)
        ):
            self._index[key] = None
        elif timestamps is not None:
            timestamps.add(played_at)

    def times_for(self, key):
        """Return the known play timestamps for one item."""
        return self._times.get(key, [])

    def is_duplicate(self, key, candidate):
        """Check whether candidate falls within the window of a known play.

        Compares against the nearest known play rather than the newest one: an
        import that re-delivers a 2020 play has to be measured against the
        stored 2020 play, not against something watched last night.
        """
        if candidate is None:
            return False

        window = duplicate_play_window(self._runtimes.get(key))
        timestamps = self._index.get(key)
        if key in self._index and (
            timestamps is None
            or (candidate.tzinfo is not None and not isinstance(candidate.tzinfo, timezone))
        ):
            return any(abs(candidate - played_at) < window for played_at in self.times_for(key))
        if not timestamps:
            return False
        position = timestamps.bisect_left(candidate)
        # Only the predecessor and successor can be the nearest timestamp.
        # Chunked sorted storage also avoids whole-list shifts for reverse or
        # out-of-order imports. Keep times_for's insertion order unchanged.
        return any(
            abs(candidate - played_at) < window
            for played_at in timestamps[max(0, position - 1) : position + 1]
        )


def existing_movie_play_times(user, media_ids=None, source=None):
    """Return the movie plays already stored for this user.

    Keyed by TMDB media_id. Reads both storage shapes: the importers create an
    extra Movie row per play, while Movie.watch() creates MoviePlay rows, and a
    play recorded in either one has to suppress a duplicate of the other.
    """
    play_times = PlayTimes()

    movies = app.models.Movie.objects.filter(user=user).select_related("item")
    if media_ids is not None:
        movies = movies.filter(item__media_id__in=media_ids)
    if source is not None:
        movies = movies.filter(item__source=source)

    movie_pks = []
    for media_id, runtime_minutes, end_date, pk in movies.values_list(
        "item__media_id",
        "item__runtime_minutes",
        "end_date",
        "pk",
    ):
        play_times.add(media_id, end_date, runtime_minutes)
        movie_pks.append((pk, media_id))

    if movie_pks:
        media_id_by_pk = dict(movie_pks)
        plays = app.models.MoviePlay.objects.filter(
            movie_id__in=media_id_by_pk,
            end_date__isnull=False,
        ).values_list("movie_id", "end_date")
        for movie_pk, end_date in plays:
            play_times.add(media_id_by_pk[movie_pk], end_date)

    return play_times


def existing_episode_play_times(user, media_ids=None, source=None):
    """Return the episode plays already stored for this user.

    Keyed by (media_id, season_number, episode_number).
    """
    play_times = PlayTimes()

    episodes = app.models.Episode.objects.filter(
        related_season__user=user,
        end_date__isnull=False,
    )
    if media_ids is not None:
        episodes = episodes.filter(item__media_id__in=media_ids)
    if source is not None:
        episodes = episodes.filter(item__source=source)

    for (
        media_id,
        season_number,
        episode_number,
        runtime_minutes,
        end_date,
    ) in episodes.values_list(
        "item__media_id",
        "item__season_number",
        "item__episode_number",
        "item__runtime_minutes",
        "end_date",
    ):
        play_times.add(
            (media_id, season_number, episode_number),
            end_date,
            runtime_minutes,
        )

    return play_times
