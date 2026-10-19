"""Bounded reads for explicit rating export; delivery uses the shared outbox."""

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Coalesce

from app.models import TV, Episode, Item, Movie
from integrations.models import (
    CAPABILITY_RATING_PUSH,
    RatingSyncEdit,
    SyncBinding,
    SyncDirection,
)
from integrations.state.outbound import enqueue_rating_change

EXPORT_BATCH_SIZE = 100


def _latest_rating(user, item):
    """Choose the latest edited rating, including durable episode clears."""
    model = {"movie": Movie, "tv": TV, "episode": Episode}[item.media_type]
    rows = (
        Episode.ratings.filter(related_season__user=user, item=item)
        if model is Episode
        else model.objects.filter(user=user, item=item)
    )
    latest = (
        rows.filter(Q(score__isnull=False) | Q(scored_at__isnull=False))
        .annotate(
            rating_time=Coalesce("scored_at", "created_at"),
        )
        .order_by("-rating_time", "-pk")
        .values("score", "rating_time")
        .first()
    )
    edit = RatingSyncEdit.objects.filter(user=user, item=item).first()
    if edit and (latest is None or edit.edited_at >= latest["rating_time"]):
        return True, edit.score
    return (True, latest["score"]) if latest else (False, None)


@shared_task(name="Export TMDb ratings", queue="celery")
def export_tmdb_ratings(user_id):
    """Export one item per destination, re-reading under the direct-edit lock."""
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return 0
    rated = Q(score__isnull=False) | Q(scored_at__isnull=False)
    items = Item.objects.filter(media_type__in=["movie", "tv", "episode"]).filter(
        Exists(Movie.objects.filter(user=user, item_id=OuterRef("pk")).filter(rated))
        | Exists(TV.objects.filter(user=user, item_id=OuterRef("pk")).filter(rated))
        | Exists(
            Episode.ratings.filter(
                related_season__user=user, item_id=OuterRef("pk")
            ).filter(rated)
        )
        | Exists(RatingSyncEdit.objects.filter(user=user, item_id=OuterRef("pk"))),
    )
    upper_id = items.order_by("-pk").values_list("pk", flat=True).first()
    if upper_id is None:
        return 0
    items = items.filter(pk__lte=upper_id)
    last_id = 0
    exported = 0
    while batch := list(
        items.filter(pk__gt=last_id).order_by("pk")[:EXPORT_BATCH_SIZE]
    ):
        for item in batch:
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user_id)
                bindings = SyncBinding.objects.filter(user=user, client_kind="tmdb")
                if not any(
                    binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_RATING_PUSH)
                    for binding in bindings
                ):
                    return exported
                found, score = _latest_rating(user, item)
                if found:
                    # Enqueue only the explicitly requested destination; the
                    # public shared helper otherwise fans out to all providers.
                    exported += len(
                        enqueue_rating_change(user, item, score, client_kind="tmdb")
                    )
        last_id = batch[-1].pk
    return exported
