"""Background tasks for durable metadata snapshots."""

from datetime import timedelta

from celery import shared_task
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from app.metadata_snapshots import build_metadata_identity, get_metadata_policy
from app.models import Item, MetadataSnapshot
from app.providers import services


@shared_task(name="Refresh metadata snapshot", ignore_result=True)
def refresh_metadata_snapshot(
    media_type,
    media_id,
    source,
    season_numbers=None,
    episode_number=None,
    language=None,
    edition_id=None,
):
    """Refresh one identity while preserving its last-known-good payload."""
    services.get_media_metadata(
        media_type,
        media_id,
        source,
        season_numbers,
        episode_number,
        language,
        edition_id,
        _floppy_refresh=True,
        _floppy_origin=MetadataSnapshot.Origin.REFRESH,
    )


@shared_task(name="Prune metadata snapshots", ignore_result=True)
def prune_metadata_snapshots(batch_size=5000):
    """Delete expired snapshots only when no durable Item can use them."""
    policy = get_metadata_policy()
    batch_size = max(int(batch_size), 0)
    if not policy.retention_days or not batch_size:
        return 0

    cutoff = timezone.now() - timedelta(days=policy.retention_days)
    item_match = Item.objects.filter(
        media_id=OuterRef("media_id"),
        source=OuterRef("source"),
    ).filter(
        Q(media_type=OuterRef("media_type"))
        | Q(
            media_type="tv",
            source=OuterRef("source"),
        ),
    )
    candidates = (
        MetadataSnapshot.objects.annotate(has_item=Exists(item_match))
        .filter(has_item=False, updated_at__lt=cutoff)
        .order_by("pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    candidate_ids = list(candidates)
    if not candidate_ids:
        return 0
    deleted, _ = MetadataSnapshot.objects.filter(pk__in=candidate_ids).delete()
    return deleted


def snapshot_task_identity(**kwargs):
    """Return the canonical identity used by task callers and tests."""
    return build_metadata_identity(**kwargs)
