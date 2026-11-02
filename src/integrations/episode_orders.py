"""Resolve external episode identities before integration writes."""

from django.db import transaction

from app import fork_services_play_dedupe as play_dedupe
from app.models import Episode
from integrations.external_references import save_observation


def portable_order(order):
    """Describe an order without using this database's primary keys."""
    if order is None:
        return None
    return {
        "show": {
            "media_id": order.show.media_id,
            "source": order.show.source,
            "library_media_type": order.show.library_media_type,
            "title": order.show.title,
            "image": order.show.image,
        },
        "provider": order.provider,
        "series_id": order.series_id,
        "key": order.key,
        "label": order.label,
        "catalogue": order.catalogue,
        "revision": order.revision,
    }


def restore_order(payload):
    """Restore an immutable catalogue under a local order identity."""
    from app.models import EpisodeOrder, Item

    show_data = payload["show"]
    show, _ = Item.objects.get_or_create(
        media_id=show_data["media_id"],
        source=show_data["source"],
        media_type="tv",
        library_media_type=show_data.get("library_media_type", "tv"),
        defaults={"title": show_data["title"], "image": show_data.get("image", "")},
    )
    order, _ = EpisodeOrder.objects.get_or_create(
        show=show,
        provider=payload["provider"],
        series_id=payload["series_id"],
        key=payload["key"],
        revision=payload["revision"],
        defaults={"label": payload["label"], "catalogue": payload["catalogue"]},
    )
    return order


def resolve_incoming(user, media_id, source, season, episode, *, integration):
    """Return ordered targets, None for legacy tracking, or [] for review."""
    from app.services.order_resolution import (
        OrderResolutionError,
        resolve_incoming_episode,
    )

    try:
        return resolve_incoming_episode(user, media_id, source, season, episode)
    except OrderResolutionError:
        save_observation(
            user,
            integration,
            "",
            source,
            f"{media_id}:{season}:{episode}",
            "episode",
            metadata={"season_number": season, "episode_number": episode},
            needs_review=True,
        )
        return []


def season_for_target(user, item, *, prepare_only=False):
    """Return a target season using the application's order-aware resolver."""
    from app.fork_services_episode import resolve_or_create_season

    return resolve_or_create_season(
        user,
        item.media_id,
        item.source,
        item.season_number,
        item.library_media_type,
        prepare_only=prepare_only,
    )


@transaction.atomic
def apply_targets(user, targets, *, watched_at=None, unplayed=False):
    """Apply all components atomically, keeping the existing play deduplication."""
    from app.services.unwatch import retract_watch

    for item in targets:
        if unplayed:
            retract_watch(user, item)
        elif watched_at is not None:
            existing = play_dedupe.existing_episode_play_times(
                user, media_ids=[item.media_id], source=item.source,
            )
            key = (item.media_id, item.season_number, item.episode_number)
            if not existing.is_duplicate(key, watched_at):
                Episode.objects.create(
                    item=item,
                    related_season=season_for_target(user, item),
                    end_date=watched_at,
                )
