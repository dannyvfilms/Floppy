"""Build related detail cards without owning request access or fragment decisions."""

import logging

from django.conf import settings

from app import helpers
from app.models import Item, MediaTypes, Sources
from app.providers import services
from app.services import metadata_resolution

logger = logging.getLogger(__name__)


def enrich_detail_seasons(
    media_metadata, *, media_id, source, user, detail_item, render_secondary_only
):
    """Enrich season metadata in place; defer provider card fetches to the fragment."""
    details = media_metadata.get("details")
    if not isinstance(details, dict):
        details = {}
        media_metadata["details"] = details

    related = media_metadata.setdefault("related", {})
    seasons = related.setdefault("seasons", [])
    has_specials = any(season.get("season_number") == 0 for season in seasons)
    show_title = Item._normalize_title_value(media_metadata.get("title"))

    if (
        render_secondary_only
        and source == Sources.TMDB.value
        and media_metadata.get("tvdb_id")
        and not has_specials
    ):
        try:
            specials_metadata = services.get_media_metadata(
                "tv_with_seasons",
                media_id,
                source,
                [0],
                language=metadata_resolution.metadata_language_default(
                    user, detail_item
                ),
            )
            if isinstance(specials_metadata, dict) and specials_metadata.get(
                "season/0"
            ):
                enriched_related = specials_metadata.get("related") or {}
                enriched_seasons = enriched_related.get("seasons")
                if isinstance(enriched_seasons, list):
                    related["seasons"] = enriched_seasons
                    seasons = enriched_seasons
        except services.ProviderAPIError:
            logger.warning(
                "Skipping specials enrichment for media_id=%s due to provider API error",
                media_id,
            )

    if (
        render_secondary_only
        and seasons
        and source in {Sources.TMDB.value, Sources.TVDB.value}
    ):
        season_numbers = sorted(
            {
                season_number
                for season in seasons
                for season_number in [season.get("season_number")]
                if season_number is not None
            },
        )
        if season_numbers:
            try:
                grouped_season_metadata = services.get_media_metadata(
                    "tv_with_seasons",
                    media_id,
                    source,
                    season_numbers,
                    language=metadata_resolution.metadata_language_default(
                        user, detail_item
                    ),
                )
            except services.ProviderAPIError:
                grouped_season_metadata = None
                logger.warning(
                    "Skipping season card enrichment for media_id=%s due to provider API error",
                    media_id,
                )
            if isinstance(grouped_season_metadata, dict):
                for season in seasons:
                    season_number = season.get("season_number")
                    season_payload = grouped_season_metadata.get(
                        f"season/{season_number}",
                    )
                    if not isinstance(season_payload, dict):
                        continue

                    detailed_title = Item._normalize_title_value(
                        season_payload.get("season_title"),
                    )
                    if detailed_title and detailed_title != show_title:
                        season["season_title"] = detailed_title
                    elif season_number == 0:
                        season["season_title"] = "Specials"
                    elif season_number is not None:
                        season["season_title"] = f"Season {season_number}"

                    payload_details = season_payload.get("details") or {}
                    if season.get("episode_count") in (None, ""):
                        season["episode_count"] = payload_details.get(
                            "episodes"
                        ) or season_payload.get("max_progress")
                    if season.get("max_progress") in (None, ""):
                        season["max_progress"] = season_payload.get(
                            "max_progress",
                        )
                    merged_details = dict(season.get("details") or {})
                    if merged_details.get("episodes") in (None, ""):
                        merged_details["episodes"] = (
                            season.get("episode_count")
                            or payload_details.get("episodes")
                            or season_payload.get("max_progress")
                        )
                    if merged_details.get("first_air_date") in (None, ""):
                        merged_details["first_air_date"] = payload_details.get(
                            "first_air_date",
                        )
                    season["details"] = merged_details
                    if season.get("first_air_date") in (None, ""):
                        season["first_air_date"] = payload_details.get(
                            "first_air_date",
                        )
                    if season.get("image") in (None, "", settings.IMG_NONE):
                        season["image"] = season_payload.get("image") or season.get(
                            "image",
                        )

    return details, seasons


def drop_recommendations_if_hidden(request, metadata):
    """Remove the recommendations section when the viewer turned it off.

    Runs before enrichment so the per-card tracking lookups are skipped too.
    """
    if getattr(request.user, "show_recommendations", True):
        return
    related = metadata.get("related")
    if related and "recommendations" in related:
        metadata["related"] = {
            name: items for name, items in related.items() if name != "recommendations"
        }


def enrich_detail_related_cards(request, media_metadata, *, media_type, tracking_user):
    """Attach tracking and season labels using the owner selected by the view."""
    for section_name, related_items in media_metadata["related"].items():
        if related_items:
            enriched_related_items = helpers.enrich_items_with_user_data(
                request,
                related_items,
                section_name=section_name,
                user=tracking_user,
                library_media_type=(
                    MediaTypes.ANIME.value
                    if media_type == MediaTypes.ANIME.value
                    and section_name == "seasons"
                    else None
                ),
            )
            if section_name == "seasons":
                for enriched_item, raw_item in zip(
                    enriched_related_items,
                    related_items,
                    strict=False,
                ):
                    if not isinstance(raw_item, dict):
                        continue
                    season_title = Item._normalize_title_value(
                        raw_item.get("season_title"),
                    )
                    show_title = Item._normalize_title_value(raw_item.get("title"))
                    if season_title and season_title != show_title:
                        enriched_item["card_title"] = season_title
                        continue

                    season_number = raw_item.get("season_number")
                    try:
                        season_number = (
                            int(season_number) if season_number is not None else None
                        )
                    except (TypeError, ValueError):
                        season_number = None

                    if season_number == 0:
                        enriched_item["card_title"] = "Specials"
                    elif season_number is not None:
                        enriched_item["card_title"] = f"Season {season_number}"

            # For anime shows, tag season items so media_url routes to anime season URLs
            if section_name == "seasons" and media_type == MediaTypes.ANIME.value:
                for enriched_item in enriched_related_items:
                    item_dict = enriched_item.get("item")
                    if isinstance(item_dict, dict):
                        item_dict["route_media_type"] = MediaTypes.ANIME.value

            media_metadata["related"][section_name] = enriched_related_items
