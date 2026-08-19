# FORK: metadata-management and score endpoints mirroring web-only actions
# (metadata_sync_views, score_views). URL wiring lives in fork_urls.py.
import logging
from decimal import Decimal, InvalidOperation
from http import HTTPStatus as HTTP  # noqa: N814

from django.apps import apps
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import custom_metadata, history_cache
from app import metadata_sync_views as web_metadata_views
from app.models import (
    Episode,
    Item,
    MediaTypes,
    MetadataProviderPreference,
    Season,
    Sources,
)
from app.services import metadata_resolution

from .helpers import check_valid_type
from .schema import MEDIA_TYPE_PARAM, MEDIA_TYPE_TV_ONLY_PARAM

logger = logging.getLogger(__name__)


def _owned_media_queryset(user, item):
    """Return the user's tracked-media rows for an item.

    Episode rows have no `user` column -- ownership is inherited from the
    related season -- so filtering them by `user=` raises FieldError and turns
    every episode metadata override into a 500.
    """
    media_model = apps.get_model("app", item.media_type)
    if item.media_type == MediaTypes.EPISODE.value:
        return media_model.objects.filter(related_season__user=user, item=item)
    return media_model.objects.filter(user=user, item=item)


def _get_owned_tracked_item(user, item_id):
    """Return the Item if the user tracks it, else None."""
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        return None
    if not _owned_media_queryset(user, item).exists():
        return None
    return item


# /api/v1/metadata/items/[item_id]/image/
class ItemImageView(drf_views.APIView):
    """Override the stored image URL for a tracked item."""

    def patch(self, request, item_id):
        """Set the item's image URL (mirrors web update_item_image)."""
        item = _get_owned_tracked_item(request.user, item_id)
        if item is None:
            return Response(
                {"detail": "Item not found in your library."},
                status=HTTP.NOT_FOUND,
            )

        image_url = (request.data.get("image_url") or "").strip()
        if not image_url:
            return Response(
                {"detail": "'image_url' is required."},
                status=HTTP.BAD_REQUEST,
            )

        if item.image != image_url:
            item.image = image_url
            item.save(update_fields=["image"])
        return Response(
            {"id": item.id, "image": item.image},
            status=HTTP.OK,
        )


# /api/v1/metadata/items/[item_id]/
class ItemMetadataView(drf_views.APIView):
    """Override custom metadata for a tracked manual item."""

    def patch(self, request, item_id):
        """Apply custom-metadata overrides (mirrors update_manual_item_metadata)."""
        item = _get_owned_tracked_item(request.user, item_id)
        if item is None:
            return Response(
                {"detail": "Item not found in your library."},
                status=HTTP.NOT_FOUND,
            )

        if not custom_metadata.supports_custom_metadata(item):
            return Response(
                {"detail": "Metadata overrides are not available for this item."},
                status=HTTP.BAD_REQUEST,
            )

        form = custom_metadata.ManualMetadataForm(request.data, item=item)
        if not form.is_valid():
            return Response(
                {"detail": "Invalid metadata.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        update_fields = form.save()
        return Response(
            {"id": item.id, "updated_fields": sorted(update_fields or [])},
            status=HTTP.OK,
        )


# /api/v1/media/[media_type]/[source]/[media_id]/provider-preference/
class MediaProviderPreferenceView(drf_views.APIView):
    """Read or set the metadata display-provider override for an item."""

    def _get_item(self, media_type, source, media_id):
        tracking_media_type = metadata_resolution.get_tracking_media_type(
            media_type,
            source=source,
        )
        lookup = {
            "media_id": media_id,
            "source": source,
            "media_type": tracking_media_type,
        }
        if metadata_resolution.is_grouped_anime_route(media_type, source=source):
            lookup["library_media_type"] = MediaTypes.ANIME.value
        return Item.objects.filter(**lookup).first()

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def get(self, request, media_type, source, media_id):
        """Return the current provider preference and available options."""
        if not check_valid_type(media_type):
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )
        item = self._get_item(media_type, source, media_id)
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
        preference = MetadataProviderPreference.objects.filter(
            user=request.user,
            item=item,
        ).first()
        options = [
            choice.value
            for choice in metadata_resolution.available_metadata_provider_options(
                media_type,
                identity_provider=item.source,
            )
        ]
        return Response(
            {
                "provider": preference.provider if preference else None,
                "available_providers": options,
            },
            status=HTTP.OK,
        )

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def put(self, request, media_type, source, media_id):
        """Set the provider override (mirrors update_metadata_provider_preference)."""
        if not check_valid_type(media_type):
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )
        item = self._get_item(media_type, source, media_id)
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)

        provider = (request.data.get("provider") or "").strip()
        allowed_providers = {
            choice.value
            for choice in metadata_resolution.available_metadata_provider_options(
                media_type,
                identity_provider=item.source,
            )
        }
        if provider not in allowed_providers:
            return Response(
                {
                    "detail": "That metadata provider is not available for this title.",
                    "available_providers": sorted(allowed_providers),
                },
                status=HTTP.BAD_REQUEST,
            )

        supports_custom = custom_metadata.supports_custom_provider(media_type)
        if provider == Sources.MANUAL.value and supports_custom:
            current_display_metadata = (
                web_metadata_views._resolve_current_display_metadata_payload(
                    user=request.user,
                    item=item,
                    media_type=media_type,
                    media_id=media_id,
                    source=source,
                )
            )
            custom_metadata.snapshot_custom_metadata(item, current_display_metadata)

        MetadataProviderPreference.objects.update_or_create(
            user=request.user,
            item=item,
            defaults={"provider": provider},
        )
        return Response({"provider": provider}, status=HTTP.OK)


# /api/v1/media/[...]/[season_number]/episodes/[episode_number]/score/
class MediaEpisodeScoreView(drf_views.APIView):
    """Set or clear the score on all plays of an episode."""

    @extend_schema(parameters=[MEDIA_TYPE_TV_ONLY_PARAM])
    def patch(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Update the episode score (mirrors web update_episode_score).

        Body: {"score": 8.5} or {"score": null} to clear. Scores use the raw
        0-10 storage scale like the other media score fields in this API.
        """
        if media_type != MediaTypes.TV.value:
            return Response(
                {"detail": "Episodes are supported only for 'tv' media type."},
                status=HTTP.BAD_REQUEST,
            )

        season = (
            Season.objects.filter(
                item__media_id=media_id,
                item__source=source,
                item__season_number=season_number,
                item__episode_number=None,
                user=request.user,
            )
            .order_by("id")
            .first()
        )
        if season is None:
            return Response(
                {"detail": "Season not found or not tracked."},
                status=HTTP.NOT_FOUND,
            )

        if "score" not in request.data:
            return Response(
                {"detail": "'score' is required (number or null)."},
                status=HTTP.BAD_REQUEST,
            )
        raw_score = request.data.get("score")
        score = None
        if raw_score is not None:
            try:
                score = Decimal(str(raw_score))
            except (InvalidOperation, TypeError, ValueError):
                return Response(
                    {"detail": "Invalid score."},
                    status=HTTP.BAD_REQUEST,
                )
            if not (Decimal(0) <= score <= Decimal(10)):
                return Response(
                    {"detail": "Score must be between 0 and 10."},
                    status=HTTP.BAD_REQUEST,
                )

        episodes = Episode.objects.filter(
            related_season=season,
            item__episode_number=int(episode_number),
        )
        if not episodes.exists():
            return Response(
                {"detail": "Episode not tracked."},
                status=HTTP.NOT_FOUND,
            )

        episodes.update(score=score)

        # episodes.update() runs raw SQL and skips post_save, so invalidate
        # the affected history days like the web view does.
        day_keys = [
            history_cache.history_day_key(end_date)
            for end_date in episodes.values_list("end_date", flat=True)
        ]
        day_keys = [day_key for day_key in day_keys if day_key]
        if day_keys:
            history_cache.invalidate_history_days(
                request.user.id,
                day_keys=day_keys,
                logging_styles=("sessions", "repeats"),
                reason="episode_score_change",
            )

        return Response(
            {"score": str(score) if score is not None else None},
            status=HTTP.OK,
        )
