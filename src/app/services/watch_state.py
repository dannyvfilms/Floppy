"""Write-through projection and reader for canonical watched state.

The projection is a *recompute*, not a delta: given a (user, item) it reads the
legacy stores and upserts one ``WatchState`` row. That makes it idempotent, so a
double invocation is harmless and a path this module does not yet hook can be
reconciled later by calling the same function. Incremental deltas would have to
be correct at every one of the dozens of call sites that mutate tracking rows.

Projection is also how *local* decisions reach the change log. Once a user has
an active synchronizing connection, a recompute that finds the stores have moved
records that movement as a change, so every existing write path — the UI, the
API, the webhooks, the importers — emits an ordered change without any of them
being edited. Until then it writes state silently, which is what keeps an
upgrade's backfill from pushing a whole library outward.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from django.apps import apps
from django.db import transaction
from django.db.models import Max, Min

from app.models.choices import MediaTypes, Status
from app.models.watch_state import (
    WatchState,
    WatchStateChange,
    WatchStateSequence,
    calculate_state_digest,
)

logger = logging.getLogger(__name__)

# Container types have no state of their own: a show, a season, a grouped-anime
# row and a podcast show are all derived from their children, so giving them a
# row would mean maintaining the same fact twice.
CONTAINER_MEDIA_TYPES = frozenset(
    {
        MediaTypes.TV.value,
        MediaTypes.SEASON.value,
    },
)

# Types that get a row. Podcast *episodes* are absent because they have no Item
# at all — PodcastEpisode hangs off PodcastShow, not off the catalog — which is
# a declared capability limitation rather than an oversight.
PROJECTED_MEDIA_TYPES = frozenset(
    {
        MediaTypes.MOVIE.value,
        MediaTypes.EPISODE.value,
        MediaTypes.ANIME.value,
        MediaTypes.MANGA.value,
        MediaTypes.BOOK.value,
        MediaTypes.COMIC.value,
        MediaTypes.COMIC_ISSUE.value,
        MediaTypes.GAME.value,
        MediaTypes.BOARDGAME.value,
        MediaTypes.MUSIC.value,
        MediaTypes.PODCAST.value,
    },
)

_SUSPEND_PROJECTION = ContextVar("suspend_watch_state_projection", default=False)


@contextmanager
def suspend_projection():
    """Skip projection writes inside a bulk mutation.

    Importers and library repairs touch thousands of rows and would otherwise
    pay a recompute per row. Callers are responsible for projecting the affected
    items once on the way out.
    """
    token = _SUSPEND_PROJECTION.set(True)
    try:
        yield
    finally:
        _SUSPEND_PROJECTION.reset(token)


def projection_suspended() -> bool:
    """Return whether projection writes are currently suspended."""
    return _SUSPEND_PROJECTION.get()


def allocate_sequence(user) -> int:
    """Return the next server sequence for this user.

    Locks the user's allocator row, so sequence order equals commit order for
    that user. Callers must already be inside the transaction that writes the
    change, otherwise the ordering guarantee is lost.
    """
    sequence_row, _ = WatchStateSequence.objects.get_or_create(user=user)
    sequence_row = WatchStateSequence.objects.select_for_update().get(
        pk=sequence_row.pk,
    )
    sequence_row.last_sequence += 1
    sequence_row.save(update_fields=["last_sequence"])
    return sequence_row.last_sequence


class ProjectedState:
    """The state derived from the legacy stores for one (user, item)."""

    __slots__ = ("first_watched_at", "last_watched_at", "play_count", "watched")

    def __init__(self, *, watched, play_count, first_watched_at, last_watched_at):
        """Store the derived values."""
        self.watched = watched
        self.play_count = play_count
        self.first_watched_at = first_watched_at
        self.last_watched_at = last_watched_at


def _derive_movie(user, item):
    """Derive movie state, merging both play storage shapes.

    Movies are recorded two ways: importers create an extra Movie row per play,
    while Movie.watch() creates MoviePlay rows and lazily backfills the row's
    original end_date as a play. A row therefore contributes its own plays when
    it has any, and otherwise contributes its end_date as a single play.
    """
    movie_model = apps.get_model(app_label="app", model_name=MediaTypes.MOVIE.value)
    rows = movie_model.objects.filter(user=user, item=item).prefetch_related("plays")

    dates = []
    play_count = 0
    completed = False
    for row in rows:
        play_dates = [play.end_date for play in row.plays.all() if play.end_date]
        if play_dates:
            play_count += len(play_dates)
            dates.extend(play_dates)
        elif row.end_date:
            play_count += 1
            dates.append(row.end_date)
        if row.status == Status.COMPLETED.value:
            completed = True

    return ProjectedState(
        watched=bool(play_count) or completed,
        play_count=play_count,
        first_watched_at=min(dates) if dates else None,
        last_watched_at=max(dates) if dates else None,
    )


def _derive_episode(user, item):
    """Derive episode state.

    Every Episode row is one watch, and a dropped row is explicitly not one, so
    the play count is the number of undropped rows — the same rule the episode
    checkmark uses through ``app_tags.watched_count``.
    """
    episode_model = apps.get_model(app_label="app", model_name=MediaTypes.EPISODE.value)
    rows = episode_model.objects.filter(
        item=item,
        related_season__user=user,
        dropped=False,
    )

    dates = [row.end_date for row in rows if row.end_date]
    play_count = rows.count()

    return ProjectedState(
        watched=bool(play_count),
        play_count=play_count,
        first_watched_at=min(dates) if dates else None,
        last_watched_at=max(dates) if dates else None,
    )


def _derive_flat(user, item):
    """Derive state for a type where a repeat is a duplicate row."""
    model = apps.get_model(app_label="app", model_name=item.media_type)
    rows = model.objects.filter(user=user, item=item)

    completed_dates = []
    play_count = 0
    for row in rows:
        if row.status == Status.COMPLETED.value:
            play_count += 1
            if row.end_date:
                completed_dates.append(row.end_date)

    return ProjectedState(
        watched=bool(play_count),
        play_count=play_count,
        first_watched_at=min(completed_dates) if completed_dates else None,
        last_watched_at=max(completed_dates) if completed_dates else None,
    )


def derive_state(user, item):
    """Return the state the legacy stores currently describe."""
    if item.media_type == MediaTypes.MOVIE.value:
        return _derive_movie(user, item)
    if item.media_type == MediaTypes.EPISODE.value:
        return _derive_episode(user, item)
    return _derive_flat(user, item)


def _should_emit_changes(user) -> bool:
    """Return whether this user's local movements are recorded as changes."""
    return WatchStateSequence.objects.filter(user=user, emit_changes=True).exists()


def _project_as_change(user, item, derived):
    """Record a local movement the legacy stores have already made.

    The stores are the decision here — the row has already been written — so
    this only gives that decision a sequence, a revision and a provenance. When
    the derived state already matches, record_state_change writes nothing.
    """
    from app.models.watch_state import WatchStateOrigin

    result = record_state_change(
        user,
        item,
        watched=derived.watched,
        play_count=derived.play_count,
        watched_at=derived.last_watched_at,
        origin_kind=WatchStateOrigin.LOCAL_UI.value,
        origin_key="local",
    )
    state = result.state
    if state is not None and state.first_watched_at != derived.first_watched_at:
        state.first_watched_at = derived.first_watched_at
        state.save(update_fields=["first_watched_at", "updated_at"])
    return state


def project_watch_state(
    user,
    item,
    *,
    origin_kind=None,
    origin_key="",
    record_changes=True,
):
    """Recompute and store canonical state for one (user, item).

    Returns the stored row, or None when the item is not projected or projection
    is suspended. Deliberately does not swallow exceptions: a silently stale
    projection is worse than a loud failure, because the sync engine will later
    treat it as evidence of what the user believes.

    ``record_changes=False`` writes state without logging a decision. Backfill
    needs it: those rows were already there, and calling them new decisions
    would deliver a user's whole library outward the moment they upgraded.
    """
    if user is None or item is None or projection_suspended():
        return None
    if item.media_type not in PROJECTED_MEDIA_TYPES:
        return None

    from app.models.watch_state import WatchStateOrigin

    derived = derive_state(user, item)
    digest = calculate_state_digest(
        derived.watched,
        derived.play_count,
        derived.last_watched_at,
    )

    if record_changes and _should_emit_changes(user):
        return _project_as_change(user, item, derived)

    state, created = WatchState.objects.get_or_create(
        user=user,
        item=item,
        defaults={
            "watched": derived.watched,
            "play_count": derived.play_count,
            "first_watched_at": derived.first_watched_at,
            "last_watched_at": derived.last_watched_at,
            "state_digest": digest,
            "origin_kind": origin_kind or WatchStateOrigin.BACKFILL.value,
            "origin_key": origin_key,
        },
    )
    if created or state.state_digest == digest:
        return state

    state.watched = derived.watched
    state.play_count = derived.play_count
    state.first_watched_at = derived.first_watched_at
    state.last_watched_at = derived.last_watched_at
    state.state_digest = digest
    if origin_kind:
        state.origin_kind = origin_kind
        state.origin_key = origin_key
    state.save(
        update_fields=[
            "watched",
            "play_count",
            "first_watched_at",
            "last_watched_at",
            "state_digest",
            "origin_kind",
            "origin_key",
            "updated_at",
        ],
    )
    return state


def project_watch_state_for_change(user, item, **kwargs):
    """Project after a tracking row changed.

    Runs inside the caller's transaction rather than deferring to commit, for
    two reasons: a view that saves and then reads effective state must not see
    the value from before its own write, and a rollback has to take the
    projection with it. The cost is a recompute per save, which is why bulk
    paths wrap themselves in ``suspend_projection`` and project once at the end.
    """
    if user is None or item is None or projection_suspended():
        return
    project_watch_state(user, item, **kwargs)


class RevisionConflictError(Exception):
    """A caller's expected revision no longer matches the stored one."""


class RecordedChange:
    """The outcome of asking to record a state change."""

    __slots__ = ("change", "replayed", "state", "unchanged")

    def __init__(self, *, state, change=None, replayed=False, unchanged=False):
        """Store the outcome."""
        self.state = state
        self.change = change
        self.replayed = replayed
        self.unchanged = unchanged

    @property
    def applied(self):
        """Return whether this call moved the state."""
        return self.change is not None and not self.replayed


@transaction.atomic
def record_state_change(
    user,
    item,
    *,
    watched,
    origin_kind,
    origin_key="",
    play_count=None,
    watched_at=None,
    kind=None,
    origin_event_id=None,
    origin_observed_at=None,
    correlation_id=None,
    causation_id=None,
    expected_revision=None,
):
    """Record one decision about state, in server order.

    This is the only writer of ``WatchStateChange``. Three outcomes matter to
    callers and are distinguished on the result rather than by exception:

    - *replayed*: this exact provider event was already applied, so the earlier
      change is returned and nothing is written. A retry is not a rewatch.
    - *unchanged*: the requested state is the state we already hold. Agreement
      is not an event, so no change row is written.
    - *applied*: the state moved, and the returned change records the move.

    ``expected_revision`` is the optimistic-concurrency check an external client
    uses (``If-Match``): passing a stale revision raises rather than clobbering
    a decision the caller has not seen.
    """
    from app.models.watch_state import (
        WatchStateChange,
        WatchStateChangeKind,
    )

    kind = kind or WatchStateChangeKind.UPSERT.value

    if origin_event_id:
        replayed = WatchStateChange.objects.filter(
            user=user,
            origin_key=origin_key,
            origin_event_id=origin_event_id,
        ).first()
        if replayed is not None:
            return RecordedChange(
                state=effective_state(user, item),
                change=replayed,
                replayed=True,
            )

    state, _created = WatchState.objects.get_or_create(user=user, item=item)
    state = WatchState.objects.select_for_update().get(pk=state.pk)

    if expected_revision is not None and expected_revision != state.revision:
        msg = (
            f"Expected revision {expected_revision} but state is at "
            f"{state.revision}"
        )
        raise RevisionConflictError(msg)

    if play_count is None:
        play_count = state.play_count
    if watched_at is None:
        watched_at = state.last_watched_at

    digest = calculate_state_digest(watched, play_count, watched_at)
    if digest == state.state_digest:
        return RecordedChange(state=state, unchanged=True)

    sequence = allocate_sequence(user)
    change = WatchStateChange.objects.create(
        user=user,
        item=item,
        sequence=sequence,
        revision=state.revision + 1,
        previous_revision=state.revision or None,
        kind=kind,
        watched=watched,
        play_count=play_count,
        watched_at=watched_at,
        state_digest=digest,
        origin_kind=origin_kind,
        origin_key=origin_key,
        origin_event_id=origin_event_id,
        origin_observed_at=origin_observed_at,
        correlation_id=correlation_id or uuid4(),
        causation_id=causation_id,
    )

    state.watched = watched
    state.play_count = play_count
    state.last_watched_at = watched_at
    if watched and state.first_watched_at is None:
        state.first_watched_at = watched_at
    state.revision = change.revision
    state.sequence = change.sequence
    state.state_digest = digest
    state.origin_kind = origin_kind
    state.origin_key = origin_key
    state.save(
        update_fields=[
            "watched",
            "play_count",
            "first_watched_at",
            "last_watched_at",
            "revision",
            "sequence",
            "state_digest",
            "origin_kind",
            "origin_key",
            "updated_at",
        ],
    )

    return RecordedChange(state=state, change=change)


def changes_since(user, sequence, *, limit=100):
    """Return this user's changes after ``sequence``, in server order."""
    return list(
        WatchStateChange.objects.filter(user=user, sequence__gt=sequence).order_by(
            "sequence",
        )[:limit],
    )


def retained_change_range(user):
    """Return the (oldest, newest) sequence still held for ``user``.

    ``(None, None)`` when nothing is retained. A client whose cursor falls below
    ``oldest`` has been compacted past and must re-snapshot: serving it the
    remaining tail would look like a successful catch-up while silently dropping
    everything in between.
    """
    bounds = WatchStateChange.objects.filter(user=user).aggregate(
        oldest=Min("sequence"),
        newest=Max("sequence"),
    )
    return bounds["oldest"], bounds["newest"]


def effective_state(user, item):
    """Return the canonical state for one (user, item), or None."""
    return WatchState.objects.filter(user=user, item=item).first()


def effective_states(user, items):
    """Return canonical states keyed by item id for a set of items."""
    return {
        state.item_id: state
        for state in WatchState.objects.filter(user=user, item__in=items)
    }
