"""Retract a watch without destroying the record that it happened.

Marking something unwatched and deleting its history are different operations
and must stay different. Today a provider's "mark unplayed" runs a bare
``.delete()`` over every matching row, so one click in Jellyfin can remove a
decade of rewatches — and because those filters are hardcoded to TMDB, on a
TVDB-sourced or grouped-anime item the same click silently does nothing at all.

Retraction here reverts the *state* the user sees and deletes only plays that
can be attributed to a specific recorded event. Anything unattributable is
preserved and surfaced, because a play we cannot identify is far more likely to
be someone's genuine history than the one the provider means.
"""

import logging

from django.db import transaction

from app.models import MediaTypes, Status

logger = logging.getLogger(__name__)


class RetractionResult:
    """What a retraction actually did."""

    __slots__ = ("attributable", "deleted_plays", "preserved_plays", "rows_reverted")

    def __init__(
        self,
        *,
        deleted_plays=0,
        preserved_plays=0,
        rows_reverted=0,
        attributable=True,
    ):
        """Store the outcome."""
        self.deleted_plays = deleted_plays
        self.preserved_plays = preserved_plays
        self.rows_reverted = rows_reverted
        self.attributable = attributable


def _revert_status(row):
    """Move a completed tracking row back to in-progress without deleting it."""
    if row.status != Status.COMPLETED.value:
        return False
    row.status = Status.IN_PROGRESS.value
    row.end_date = None
    row.save(update_fields=["status", "end_date"])
    return True


@transaction.atomic
def retract_movie_watch(user, item, *, external_id=None):
    """Retract a movie watch, keeping unattributable plays.

    With an ``external_id`` this removes exactly the play that event created.
    Without one it reverts the row's status and keeps every play, because
    "this movie is not watched any more" is not evidence about which viewing
    was wrong.
    """
    from app.models import Movie, MoviePlay

    rows = list(Movie.objects.filter(user=user, item=item))
    if not rows:
        return RetractionResult()

    deleted = 0
    if external_id:
        deleted, _ = MoviePlay.objects.filter(
            movie__in=rows,
            external_id=external_id,
        ).delete()

    preserved = MoviePlay.objects.filter(movie__in=rows).count()
    reverted = sum(_revert_status(row) for row in rows)

    return RetractionResult(
        deleted_plays=deleted,
        preserved_plays=preserved,
        rows_reverted=reverted,
        attributable=bool(external_id and deleted),
    )


@transaction.atomic
def retract_episode_watch(user, item, *, watch_operation_id=None):
    """Retract an episode watch, keeping unattributable plays.

    Every ``Episode`` row is one watch, so there is no status to revert
    independently of the rows. With a ``watch_operation_id`` exactly the
    matching play is removed. Without one the most recent play is dropped and
    the rest are kept — a provider saying "unwatched" is at most evidence about
    the latest viewing, never about all of them.
    """
    from app.models import Episode

    rows = Episode.objects.filter(item=item, related_season__user=user)
    if not rows.exists():
        return RetractionResult()

    if watch_operation_id:
        target = rows.filter(watch_operation_id=watch_operation_id).first()
        attributable = target is not None
    else:
        target = rows.order_by("-end_date", "-id").first()
        attributable = False

    deleted = 0
    if target is not None:
        related_season = target.related_season
        target.delete()
        deleted = 1
        related_season._sync_status_after_episode_change()

    return RetractionResult(
        deleted_plays=deleted,
        preserved_plays=rows.count(),
        attributable=attributable,
    )


def retract_watch(user, item, *, external_id=None, watch_operation_id=None):
    """Retract a watch for any item type that has one."""
    if item.media_type == MediaTypes.MOVIE.value:
        return retract_movie_watch(user, item, external_id=external_id)
    if item.media_type == MediaTypes.EPISODE.value:
        return retract_episode_watch(
            user,
            item,
            watch_operation_id=watch_operation_id,
        )

    return _retract_flat(user, item)


@transaction.atomic
def _retract_flat(user, item):
    """Revert completed rows for a type where a repeat is a duplicate row."""
    from django.apps import apps

    model = apps.get_model(app_label="app", model_name=item.media_type)
    rows = list(model.objects.filter(user=user, item=item))
    reverted = sum(_revert_status(row) for row in rows)

    return RetractionResult(rows_reverted=reverted, attributable=False)
