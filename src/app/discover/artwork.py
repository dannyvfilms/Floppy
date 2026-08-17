"""Artwork hydration for Discover row candidates."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

from app.discover.service_helpers import MAX_ITEMS_PER_ROW
from app.models import Item, MediaTypes, Sources
from app.providers import services

if TYPE_CHECKING:
    from app.discover.schemas import CandidateItem, RowDefinition, RowResult

logger = logging.getLogger(__name__)

ROW_CACHE_TTL_SECONDS = 60 * 60
ROW_CACHE_TTL_LOCAL_SECONDS = 60 * 30

PROVIDER_ARTWORK_HYDRATION_ROW_KEYS = {
    "trending_right_now",
    "all_time_greats_unseen",
    "coming_soon",
}
PROVIDER_ARTWORK_HYDRATION_PROVIDERS = frozenset(
    {
        (MediaTypes.BOARDGAME.value, Sources.BGG.value),
        (MediaTypes.MUSIC.value, Sources.MUSICBRAINZ.value),
    },
)

# These values can remain in persisted rows or cached Discover payloads after
# the configured placeholder changes. Keep exact historical values here instead
# of importing a migration at runtime; migrations must remain deterministic.
LEGACY_IMG_NONE_VALUES = frozenset(
    {
        (
            "https://www.themoviedb.org/assets/2/v4/glyphicons/basic/"
            "glyphicons-basic-38-picture-grey-"
            "c2ebdbb057f2a7614185931650f8cee23fa137b93812ccb132b9df511df1cfac.svg"
        ),
        (
            "data:image/svg+xml;base64,"
            "PHN2ZyBpZD0iZ2x5cGhpY29ucy1iYXNpYyIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwIDAgMzIgMzIiPgogIDxwYXRoIGZpbGw9IiNiNWI1YjUiIGlkPSJwaWN0dXJlIiBkPSJNMjcuNSw1SDQuNUExLjUwMDA4LDEuNTAwMDgsMCwwLDAsMyw2LjV2MTlBMS41MDAwOCwxLjUwMDA4LDAsMCwwLDQuNSwyN2gyM0ExLjUwMDA4LDEuNTAwMDgsMCwwLDAsMjksMjUuNVY2LjVBMS41MDAwOCwxLjUwMDA4LDAsMCwwLDI3LjUsNVpNMjYsMTguNWwtNC43OTQyNS01LjIzMDFhLjk5MzgzLjk5MzgzLDAsMCAwLTEuNDQ0MjgtLjAzMTM3bC01LjM0NzQxLDUuMzQ3NDFMMTkuODI4MTIsMjRIMTdsLTQuNzkyOTEtNC43OTNhMS4wMDAyMiwxLjAwMDIyLDAsMCAwLTEuNDE0MTgsMEw2LDI0VjhIMjZabS0xNy45LTZhMi40LDIuNCwwLDEsMSwyLjQsMi40QTIuNDAwMDUsMi40MDAwNSwwLDAsMSw4LjEsMTIuNVoiLz4KPC9zdmc+Cg=="
        ),
    },
)


def _row_ttl_seconds(row_definition: RowDefinition) -> int:
    return (
        ROW_CACHE_TTL_LOCAL_SECONDS
        if row_definition.source == "local"
        else ROW_CACHE_TTL_SECONDS
    )


def _is_missing_image_value(image: str | None) -> bool:
    """Return whether an image value represents missing artwork."""
    return (
        not image
        or image == settings.IMG_NONE
        or image in LEGACY_IMG_NONE_VALUES
    )


def _is_missing_image(candidate: CandidateItem) -> bool:
    return _is_missing_image_value(candidate.image)


def _local_images_for_candidates(
    candidates: list[CandidateItem],
) -> dict[tuple[str, str, str], str]:
    """Return usable local artwork keyed by normalized candidate identity."""
    identities = {candidate.identity() for candidate in candidates}
    if not identities:
        return {}

    items = Item.objects.filter(
        media_id__in={candidate.media_id for candidate in candidates},
        media_type__in={candidate.media_type for candidate in candidates},
        source__in={candidate.source for candidate in candidates},
    ).only("media_type", "source", "media_id", "image")

    local_images = {}
    for item in items:
        identity = (item.media_type, item.source, str(item.media_id))
        if identity not in identities or _is_missing_image_value(item.image):
            continue
        local_images[identity] = item.image
    return local_images


def _hydrate_missing_artwork(
    candidates: list[CandidateItem],
    *,
    allow_remote: bool,
) -> None:
    """Hydrate missing artwork using each candidate's metadata identity."""
    missing = [candidate for candidate in candidates if _is_missing_image(candidate)]
    if not missing:
        return

    local_images = _local_images_for_candidates(missing)
    for candidate in missing:
        local_image = local_images.get(candidate.identity())
        if local_image:
            candidate.image = local_image

    if not allow_remote:
        return

    for candidate in missing:
        if not _is_missing_image(candidate):
            continue
        try:
            metadata = services.get_media_metadata(
                candidate.media_type,
                candidate.media_id,
                candidate.source,
            )
        except Exception as error:
            logger.warning(
                "discover_artwork_lookup_failed media_type=%s source=%s media_id=%s error=%s",
                candidate.media_type,
                candidate.source,
                candidate.media_id,
                error,
            )
            continue

        image = (metadata or {}).get("image")
        if not _is_missing_image_value(image):
            candidate.image = image


def _supports_provider_artwork_hydration(candidate: CandidateItem) -> bool:
    return (
        candidate.media_type,
        candidate.source,
    ) in PROVIDER_ARTWORK_HYDRATION_PROVIDERS


def _hydrate_provider_ranked_artwork(
    candidates: list[CandidateItem],
    *,
    allow_remote: bool = True,
    hydrate_limit: int = MAX_ITEMS_PER_ROW,
) -> None:
    """Hydrate missing artwork for top provider-ranked boardgame/music candidates."""
    display_candidates = [
        candidate
        for candidate in candidates[:hydrate_limit]
        if _supports_provider_artwork_hydration(candidate)
    ]
    if not display_candidates:
        return

    _hydrate_missing_artwork(display_candidates, allow_remote=allow_remote)


def _hydrate_trakt_ranked_artwork(
    media_type: str,
    candidates: list[CandidateItem],
    *,
    allow_remote: bool = True,
    hydrate_limit: int = MAX_ITEMS_PER_ROW,
) -> None:
    """Hydrate missing artwork for displayed Trakt-ranked candidates."""
    if media_type not in {
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
    }:
        return

    # Trakt ranks the row. CandidateItem.source owns the metadata identity used
    # for local and remote artwork, so a different mapping/provider can be
    # introduced without changing this hydration path.
    display_candidates = [
        candidate
        for candidate in candidates[:hydrate_limit]
        if candidate.media_type == media_type
    ]
    if not display_candidates:
        return

    _hydrate_missing_artwork(display_candidates, allow_remote=allow_remote)


def hydrate_visible_row_artwork(
    row: RowResult,
    *,
    allow_remote: bool = True,
) -> None:
    """Hydrate missing artwork for currently visible row items.

    This is used by the optimistic Discover tab-cache patching path so a
    reserve item promoted into the visible 12 can render with poster artwork
    immediately instead of waiting for a later full row rebuild.
    """
    if not row.items:
        return

    if not any(_is_missing_image(item) for item in row.items[:MAX_ITEMS_PER_ROW]):
        return

    effective_media_type = next(
        (
            candidate.media_type
            for candidate in [*row.items, *row.reserve_items]
            if candidate.media_type
        ),
        None,
    )
    if not effective_media_type:
        return

    if effective_media_type in {
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
    } and row.key in {
        "trending_right_now",
        "all_time_greats_unseen",
        "coming_soon",
    }:
        _hydrate_trakt_ranked_artwork(
            effective_media_type,
            row.items,
            allow_remote=allow_remote,
        )
        return

    if row.source == "provider" and row.key in PROVIDER_ARTWORK_HYDRATION_ROW_KEYS:
        _hydrate_provider_ranked_artwork(
            row.items,
            allow_remote=allow_remote,
        )
