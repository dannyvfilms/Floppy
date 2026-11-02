"""Explicit boundaries between provider coordinates and a user's episode order."""

# Messages are user-facing resolution details and remain beside their failure
# branch for clear integration diagnostics.
# ruff: noqa: EM101, TRY003

from app.models import TV, EpisodeOrder, Item, MediaTypes


class OrderResolutionError(ValueError):
    """An episode cannot be identified safely in the selected tracking order."""


def order_from_media_id(media_id, source=None):
    """Resolve an internal order identity without ever sending it to a provider."""
    value = str(media_id)
    if not value.startswith("order_"):
        return None
    suffix = value.removeprefix("order_")
    if not suffix.isdecimal():
        raise OrderResolutionError("Invalid episode order identity.")
    query = EpisodeOrder.objects.select_related("show").filter(pk=int(suffix))
    if source is not None:
        query = query.filter(provider=source)
    order = query.first()
    if order is None:
        raise OrderResolutionError("Episode order is unavailable.")
    return order


def active_order(user, media_id, source):
    """Return a personal order only for a positively identified tracked show."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    order = order_from_media_id(media_id, source)
    if order is not None:
        return order if TV.objects.filter(user=user, active_episode_order=order).exists() else None
    # Two index-driven lookups instead of one OR across the user's whole
    # library: the OR defeats the item index, so SQLite scans every tracked
    # show of the user.
    by_item = TV.objects.filter(
        user=user,
        active_episode_order__isnull=False,
        item__media_id=str(media_id),
        item__source=source,
    )
    order_ids = list(
        EpisodeOrder.objects.filter(
            series_id=str(media_id), provider=source,
        ).values_list("id", flat=True),
    )
    related = ("active_episode_order", "active_episode_order__show")
    found = {t.pk: t for t in by_item.select_related(*related)[:2]}
    if order_ids:
        by_order = TV.objects.filter(user=user, active_episode_order_id__in=order_ids)
        found.update({t.pk: t for t in by_order.select_related(*related)[:2]})
    matches = list(found.values())
    if len(matches) > 1:
        raise OrderResolutionError("Multiple tracked shows match this provider identity.")
    return matches[0].active_episode_order if matches else None


def resolve_incoming_episode(
    user, media_id, source, season_number, episode_number, *,
    provider_episode_id=None, source_order=None,
):
    """Translate a proven provider episode identity; never guess an offset."""
    order = active_order(user, media_id, source)
    if order is None:
        return None
    if str(media_id) == order.media_id:
        items = list(Item.objects.filter(
            episode_order=order, media_type=MediaTypes.EPISODE.value,
            season_number=season_number, episode_number=episode_number,
        ))
        if len(items) == 1:
            return items
        raise OrderResolutionError("Episode is absent from the selected order.")
    if not provider_episode_id:
        from app.providers.episode_orders import fetch_order

        catalogue = fetch_order(
            source, str(media_id),
            source_order or ("aired" if source == "tmdb" else "default"),
            user=user,
        )
        matches = [
            row for row in catalogue["episodes"]
            if row["season_number"] == season_number
            and row["episode_number"] == episode_number
        ]
        if len(matches) != 1:
            raise OrderResolutionError("Source episode needs an explicit mapping.")
        provider_episode_id = matches[0]["provider_episode_id"]
    if source == order.provider:
        items = list(Item.objects.filter(
            episode_order=order, media_type=MediaTypes.EPISODE.value,
            provider_episode_id=str(provider_episode_id),
        ))
        if len(items) == 1:
            return items
    raise OrderResolutionError("Episode needs an approved mapping to the selected order.")
