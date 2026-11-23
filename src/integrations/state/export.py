"""Queue a library's existing plays, statuses and ratings for one destination.

Shared by every destination that takes a one-off "send my existing library"
request (WeTrakr, Simkl, ...). Imported history never reaches such a service by
itself, so this is the one way it does, and only when the user asks. Everything
goes through the same outbox as a live play, so batching, rate limits, retries
and per-item results behave identically. A destination supplies only the rows it
wants, so its own task stays a few lines long.
"""

from django.db.models import Exists, Max, OuterRef, Q

from app.models import TV, Episode, Item, Movie, MoviePlay, Status
from integrations.models import (
    CAPABILITY_PLAY_PUSH,
    CAPABILITY_RATING_PUSH,
    CAPABILITY_STATUS_PUSH,
    OutboundDeliveryStatus,
    OutboundStateDelivery,
    RatingSyncEdit,
    SyncDirection,
)
from integrations.state import outbound

EXPORT_CHUNK = 500


def movie_play_sets(user):
    """Return the two querysets behind a movie's dated watches.

    Each ``MoviePlay`` is one watch. A completed ``Movie`` row with no plays
    (imported or older entries) counts once, by its own end date.
    """
    plays = MoviePlay.objects.filter(
        movie__user=user,
        movie__item__isnull=False,
        end_date__isnull=False,
    ).values_list("movie__item_id", "end_date")
    legacy = (
        Movie.objects.filter(
            user=user,
            status=Status.COMPLETED.value,
            end_date__isnull=False,
        )
        .exclude(Exists(MoviePlay.objects.filter(movie=OuterRef("pk"))))
        .values_list("item_id", "end_date")
    )
    return plays, legacy


def movie_plays(user):
    """Return ``(item_id, watched_at)`` for every dated watch of a movie."""
    plays, legacy = movie_play_sets(user)
    return [*plays, *legacy]


def episode_plays(user):
    """Return ``(item_id, watched_at)`` for every dated episode watch."""
    return Episode.objects.filter(
        Episode.watch_q(),
        related_season__user=user,
        related_season__order_archived=False,
        item__isnull=False,
        end_date__isnull=False,
    ).values_list("item_id", "end_date")


def status_sets(user):
    """Return the movie and show rows whose status is worth sending."""
    movies = Movie.objects.filter(
        user=user,
        status__in=[Status.PLANNING.value, Status.DROPPED.value],
    ).values_list("item_id", "status")
    shows = TV.objects.filter(
        user=user,
        status__in=[Status.PLANNING.value, Status.PAUSED.value, Status.DROPPED.value],
    ).values_list("item_id", "status")
    return movies, shows


def statuses(user):
    """Return ``(item_id, status)`` for movies and shows, flattened."""
    movies, shows = status_sets(user)
    return [*movies, *shows]


def rated_items(user):
    """Movies and shows this user has rated, or cleared a rating on."""
    rated = Q(score__isnull=False) | Q(scored_at__isnull=False)
    return Item.objects.filter(media_type__in=["movie", "tv"]).filter(
        Exists(Movie.objects.filter(user=user, item_id=OuterRef("pk")).filter(rated))
        | Exists(TV.objects.filter(user=user, item_id=OuterRef("pk")).filter(rated))
        | Exists(RatingSyncEdit.objects.filter(user=user, item_id=OuterRef("pk"))),
    )


def library_preview(user):
    """Return how many plays, statuses and ratings an export would queue."""
    # Counts only: this runs on a page load, so it must not read the history.
    plays = (
        sum(rows.count() for rows in movie_play_sets(user))
        + episode_plays(user).count()
    )
    undated = (
        Movie.objects.filter(
            user=user,
            status=Status.COMPLETED.value,
            end_date__isnull=True,
        )
        .exclude(
            Exists(
                MoviePlay.objects.filter(movie=OuterRef("pk"), end_date__isnull=False),
            ),
        )
        .count()
        + Episode.objects.filter(
            Episode.watch_q(),
            related_season__user=user,
            related_season__order_archived=False,
            end_date__isnull=True,
        ).count()
    )
    return {
        "plays": plays,
        "undated": undated,
        "statuses": sum(rows.count() for rows in status_sets(user)),
    }


def next_revisions(binding, operation):
    """Return the highest revision used so far for each item, for one operation."""
    return dict(
        OutboundStateDelivery.objects.filter(binding=binding, operation=operation)
        .values_list("item_id")
        .annotate(top=Max("target_revision")),
    )


def queue_deliveries(binding, user, operation, rows, revisions, *, hold):
    """Create deliveries for ``(item_id, value)`` rows; return how many."""
    created = []
    for item_id, value in rows:
        revisions[item_id] = revisions.get(item_id, 0) + 1
        payload = (
            {"watched_at": value.isoformat() if value else None}
            if operation == "play"
            else {"status": value}
        )
        created.append(
            OutboundStateDelivery(
                binding=binding,
                user=user,
                item_id=item_id,
                operation=operation,
                target_revision=revisions[item_id],
                payload=payload,
                status=OutboundDeliveryStatus.PENDING.value,
                client_event_id=f"export-{binding.pk}-{operation}-{item_id}-{revisions[item_id]}",
                next_attempt_at=hold,
            ),
        )
    OutboundStateDelivery.objects.bulk_create(created, batch_size=EXPORT_CHUNK)
    return len(created)


def undated_plays(user):
    """Return ``(item_id, None)`` for every finished watch that has no date.

    A destination that cannot show "no date" skips these unless the user chose
    otherwise; ``None`` in the payload is how the adapter learns the play is
    undated, so it never has to guess a date.
    """
    movies = (
        Movie.objects.filter(
            user=user,
            item__isnull=False,
            status=Status.COMPLETED.value,
            end_date__isnull=True,
        )
        .exclude(
            Exists(
                MoviePlay.objects.filter(movie=OuterRef("pk"), end_date__isnull=False),
            ),
        )
        .values_list("item_id", flat=True)
    )
    episodes = Episode.objects.filter(
        Episode.watch_q(),
        related_season__user=user,
        related_season__order_archived=False,
        item__isnull=False,
        end_date__isnull=True,
    ).values_list("item_id", flat=True)
    return [(item_id, None) for item_id in dict.fromkeys([*movies, *episodes])]


def queue_library(
    binding,
    user,
    *,
    client_kind,
    play_rows=None,
    status_rows=None,
    rate=False,
):
    """Queue what a destination takes, once, and return how many were queued.

    ``play_rows`` and ``status_rows`` are callables returning ``(item_id,
    value)`` rows, called only when the binding allows that kind of change. A
    play already queued (not superseded) for the same date is not queued again,
    so pressing the button twice sends nothing twice.
    """
    # Imported here: the URL modules load this file, and the task modules they
    # would pull in must stay out of web startup.
    from integrations.tasks._ratings import _latest_rating

    hold = outbound.release_time(binding.delivery_schedule)
    total = 0

    if play_rows is not None and binding.allows(
        SyncDirection.OUTBOUND.value,
        CAPABILITY_PLAY_PUSH,
    ):
        already = set(
            OutboundStateDelivery.objects.filter(binding=binding, operation="play")
            .exclude(status=OutboundDeliveryStatus.SUPERSEDED.value)
            .values_list("item_id", "payload__watched_at"),
        )
        revisions = next_revisions(binding, "play")
        rows = [
            (item_id, when)
            for item_id, when in dict.fromkeys(play_rows())
            if (item_id, when.isoformat() if when else None) not in already
        ]
        for start in range(0, len(rows), EXPORT_CHUNK):
            total += queue_deliveries(
                binding,
                user,
                "play",
                rows[start : start + EXPORT_CHUNK],
                revisions,
                hold=hold,
            )

    if status_rows is not None and binding.allows(
        SyncDirection.OUTBOUND.value,
        CAPABILITY_STATUS_PUSH,
    ):
        total += queue_deliveries(
            binding,
            user,
            "status",
            status_rows(),
            next_revisions(binding, "status"),
            hold=hold,
        )

    if rate and binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_RATING_PUSH):
        for item in rated_items(user).iterator(chunk_size=EXPORT_CHUNK):
            found, score = _latest_rating(user, item)
            if found:
                total += len(
                    outbound.enqueue_rating_change(
                        user,
                        item,
                        score,
                        client_kind=client_kind,
                    ),
                )

    if total:
        outbound.kick_flush(binding)
    return total
