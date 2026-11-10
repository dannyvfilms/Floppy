# FORK: metadata-management and score endpoints mirroring web-only actions
# (metadata_sync_views, score_views). URL wiring lives in fork_urls.py.
import base64
import binascii
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.apps import apps
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from app import custom_metadata
from app import metadata_sync_views as web_metadata_views
from app.fork_services_episode import resolve_or_create_season
from app.models import (
    BasicMedia,
    Item,
    MediaTypes,
    MetadataProviderPreference,
    Sources,
    Status,
)
from app.providers import tmdb
from app.services import metadata_resolution
from app.services.metadata_projection import project_item_metadata
from integrations.state.ratings import rating_edit

from .contract_serializers import DetailErrorSerializer
from .helpers import (
    apply_episode_score,
    body_too_large_response,
    check_valid_type,
    get_tracked_season,
    resolve_episode_coordinate_for_request,
    validate_episode_score,
)
from .schema import (
    LIBRARY_MEDIA_TYPE_PARAM,
    MEDIA_TYPE_PARAM,
    MEDIA_TYPE_TV_ONLY_PARAM,
)

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


def _metadata_response(request, **lookup):
    """Project one catalog item, adding the viewer's region watch providers."""
    item = Item.objects.filter(**lookup).first()
    if item is None:
        return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
    payload = project_item_metadata(item)
    payload["item_id"] = item.id
    names = tmdb.item_watch_provider_names(
        item,
        getattr(request.user, "watch_provider_region", ""),
    )
    if names:
        region = request.user.watch_provider_region
        payload["watch_providers"] = {region: names}
    if item.media_type == MediaTypes.TV.value:
        # Match the detail page's stored-episode runtime calculation, including
        # this viewer's dropped seasons, without fetching provider metadata.
        media = _owned_media_queryset(request.user, item).first() or apps.get_model("app", "tv")(item=item)
        BasicMedia.objects.annotate_max_progress([media], item.media_type)
        total_runtime = media.formatted_total_runtime
        if total_runtime and total_runtime != "--":
            payload["total_runtime"] = total_runtime
    return Response(payload, status=HTTP.OK)


# /api/v1/media/[type]/[source]/[id]/metadata/
class MediaMetadataView(drf_views.APIView):
    """Return stored metadata for one item by its provider identity.

    Like ``MediaStateView``, this serves every valid catalog item, tracked or
    not: the native detail page opens from Discover and search results, where
    the item is not in the caller's library yet. Stored metadata is provider
    catalog data, not user data; tracking state has its own endpoint.
    ``watch_providers`` maps the viewer's configured region to provider names
    and is omitted when no region is set or nothing streams there.
    """

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, media_type, source, media_id):
        """Project the item's stored metadata for the native detail page."""
        return _metadata_response(
            request,
            media_type=media_type,
            source=source,
            media_id=media_id,
        )


# /api/v1/media/tv/[source]/[id]/[season]/metadata/
class MediaSeasonMetadataView(drf_views.APIView):
    """Return stored metadata for one season of a show."""

    @extend_schema(
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        operation_id="retrieveMediaSeasonMetadata",
        responses={200: OpenApiTypes.OBJECT, 404: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Project the stored season Item by its number."""
        return self._project(request, media_type, source, media_id, season_number)

    @staticmethod
    def _project(request, media_type, source, media_id, season_number, episode_number=None):
        if media_type != MediaTypes.TV.value:
            return Response(
                {"detail": "Seasons and episodes are supported only for 'tv'."},
                status=HTTP.BAD_REQUEST,
            )
        lookup = {"season_number": int(season_number)}
        if episode_number is not None:
            lookup["episode_number"] = int(episode_number)
        return _metadata_response(
            request,
            media_type=(
                MediaTypes.SEASON.value
                if episode_number is None
                else MediaTypes.EPISODE.value
            ),
            source=source,
            media_id=media_id,
            **lookup,
        )


# /api/v1/media/tv/[source]/[id]/[season]/[episode]/metadata/
class MediaEpisodeMetadataView(MediaSeasonMetadataView):
    """Return stored metadata for one episode of a show."""

    @extend_schema(
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        operation_id="retrieveMediaEpisodeMetadata",
        responses={200: OpenApiTypes.OBJECT, 404: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id, season_number, episode_number):
        """Project the stored episode Item by its coordinates."""
        return self._project(
            request, media_type, source, media_id, season_number, episode_number,
        )


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
    """Read a normalized projection, or override custom metadata."""

    def get(self, request, item_id):
        """Return the normalized projection with attribution and freshness."""
        item = _get_owned_tracked_item(request.user, item_id)
        if item is None:
            return Response(
                {"detail": "Item not found in your library."},
                status=HTTP.NOT_FOUND,
            )

        return Response(project_item_metadata(item), status=HTTP.OK)

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

    @extend_schema(
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM, LIBRARY_MEDIA_TYPE_PARAM],
        responses={404: DetailErrorSerializer},
    )
    @rating_edit
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
        An episode nobody has watched is rated too: the season is tracked as
        Planning and the rating is stored without a play (it never counts as
        a watch). Clearing a score that does not exist returns 404.
        """
        if media_type != MediaTypes.TV.value:
            return Response(
                {"detail": "Episodes are supported only for 'tv' media type."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            _, coordinate_error = resolve_episode_coordinate_for_request(
                request.user,
                media_id,
                source,
                season_number,
                episode_number,
                language=metadata_resolution.metadata_language_default(request.user),
            )
        except Exception as error:
            return Response(
                {"detail": "Could not resolve episode.", "errors": str(error)},
                status=HTTP.NOT_FOUND,
            )
        if coordinate_error:
            return coordinate_error

        if "score" not in request.data:
            return Response(
                {"detail": "'score' is required (number or null)."},
                status=HTTP.BAD_REQUEST,
            )
        score, error = validate_episode_score(request.data.get("score"))
        if error:
            return error

        library_media_type = request.query_params.get("library_media_type") or None
        season = get_tracked_season(
            request.user,
            media_id,
            source,
            season_number,
            library_media_type,
        )
        if season is None and score is not None:
            # Like movies, shows and seasons, rating an untracked episode
            # starts tracking it as Planning; the rating is not a watch.
            try:
                season = resolve_or_create_season(
                    request.user,
                    media_id,
                    source,
                    int(season_number),
                    library_media_type or "",
                    status=Status.PLANNING.value,
                )
            except Exception:
                logger.exception("Could not create season for episode score.")
                return Response(
                    {"detail": "Could not resolve season."},
                    status=HTTP.NOT_FOUND,
                )
        if season is None or not apply_episode_score(season, episode_number, score):
            return Response(
                {"detail": "Episode has no rating to clear."},
                status=HTTP.NOT_FOUND,
            )

        return Response(
            {"score": str(score) if score is not None else None},
            status=HTTP.OK,
        )


def _cover_error(message, local_covers):
    raise local_covers.CoverError(message)


# /api/v1/metadata/items/[item_id]/cover/
class ItemCoverView(drf_views.APIView):
    """Local covers: pictures on offer (GET) and upload or link (POST).

    Mirrors ``app.cover_views`` (see docs/architecture/local-covers.md): the
    same storage rules, the same ownership test, one way in for both clients.
    POST takes multipart ``cover_file``, a ``cover_url`` (form or JSON) or a JSON
    ``cover_base64`` (what native clients send).
    """

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def _item(self, request, item_id):
        from app import cover_views

        item = Item.objects.filter(id=item_id).first()
        if item is None or not cover_views.user_has_item(request.user, item):
            return None
        return item

    @extend_schema(operation_id="listItemCoverCandidates", responses={200: OpenApiTypes.OBJECT})
    def get(self, request, item_id):
        """Return the covers other sources have for the item."""
        from app import cover_views, image_cache

        item = self._item(request, item_id)
        if item is None:
            return Response({"detail": "Item not found in your library."}, status=HTTP.NOT_FOUND)
        return Response({
            "current": image_cache.rewrite_image_url(item.image),
            "candidates": [
                {"title": row["title"], "image": image_cache.rewrite_image_url(row["image"])}
                for row in cover_views._candidates(request.user, item)
            ],
        })

    @staticmethod
    def _stored_cover(request, local_covers):
        """Store the picked file, base64 image or link; CoverError says what is wrong."""
        upload = request.FILES.get("cover_file")
        link = str(request.data.get("cover_url") or "").strip()
        encoded = str(request.data.get("cover_base64") or "").strip()
        too_large = "That image is larger than 10 MB."
        if encoded:
            # Native clients send the picked image as base64 in a JSON body.
            encoded = encoded.split(",", 1)[-1]
            if len(encoded) > 4 * ((local_covers.MAX_COVER_BYTES + 2) // 3):
                return _cover_error(too_large, local_covers)
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                return _cover_error("That image could not be read.", local_covers)
            if len(raw) > local_covers.MAX_COVER_BYTES:
                return _cover_error(too_large, local_covers)
            return local_covers.store_bytes(raw)
        if upload is not None:
            if upload.size > local_covers.MAX_COVER_BYTES:
                return _cover_error(too_large, local_covers)
            return local_covers.store_bytes(upload.read())
        if link:
            return local_covers.fetch_cover(link)
        return _cover_error("Choose an image or enter a link to one.", local_covers)

    @extend_schema(operation_id="setItemCover", request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, item_id):
        """Store an uploaded file or a linked image as the item's cover."""
        from app import cover_views, local_covers

        too_large = body_too_large_response(
            request, local_covers.MAX_COVER_BYTES, "That image is larger than 10 MB.",
        )
        if too_large is not None:
            return too_large
        item = self._item(request, item_id)
        if item is None:
            return Response({"detail": "Item not found in your library."}, status=HTTP.NOT_FOUND)
        try:
            value = self._stored_cover(request, local_covers)
        except local_covers.CoverError as error:
            return Response({"detail": error.message}, status=HTTP.BAD_REQUEST)
        if item.image != value:
            cover_views._set_cover(item, value)
        return Response({"id": item.id, "image": item.image}, status=HTTP.OK)


# /api/v1/metadata/items/[item_id]/hardcover-editions/
class ItemHardcoverEditionsView(drf_views.APIView):
    """Hardcover edition picker for a tracked book (mirrors the web picker, #539)."""

    def _item(self, request, item_id):
        item = Item.objects.filter(
            id=item_id, source=Sources.HARDCOVER.value, media_type=MediaTypes.BOOK.value,
        ).first()
        if item is None or _get_owned_tracked_item(request.user, item.id) is None:
            return None
        return item

    @extend_schema(operation_id="listItemHardcoverEditions", responses={200: OpenApiTypes.OBJECT})
    def get(self, request, item_id):
        """List editions, filtered by ``q``, plus the one in use."""
        from app import image_cache
        from app.models import HardcoverEditionPreference
        from app.providers import hardcover

        item = self._item(request, item_id)
        if item is None:
            return Response({"detail": "Item not found in your library."}, status=HTTP.NOT_FOUND)
        query = str(request.query_params.get("q") or "").strip().lower()
        editions = hardcover.editions(item.media_id, user=request.user)
        if query:
            editions = [
                edition for edition in editions
                if query in " ".join(
                    str(edition.get(field) or "")
                    for field in ("title", "language", "format", "publisher")
                ).lower()
            ]
        preference = HardcoverEditionPreference.objects.filter(
            user=request.user, item=item,
        ).first()
        return Response({
            "selected": preference.edition_id if preference else "",
            "results": [
                {**edition, "image": image_cache.rewrite_image_url(edition.get("image"))}
                for edition in editions
            ],
        })

    @extend_schema(operation_id="setItemHardcoverEdition", request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, item_id):
        """Remember the edition the viewer picked."""
        from django.core.cache import cache

        from app.models import HardcoverEditionPreference

        item = self._item(request, item_id)
        if item is None:
            return Response({"detail": "Item not found in your library."}, status=HTTP.NOT_FOUND)
        edition_id = str(request.data.get("edition_id") or "").strip()
        if not edition_id:
            return Response({"detail": "'edition_id' is required."}, status=HTTP.BAD_REQUEST)
        HardcoverEditionPreference.objects.update_or_create(
            user=request.user, item=item, defaults={"edition_id": edition_id},
        )
        prefix = f"{Sources.HARDCOVER.value}_{MediaTypes.BOOK.value}_{item.media_id}"
        cache.delete(prefix)
        cache.delete(f"{prefix}_{edition_id}")
        return Response({"id": item.id, "edition_id": edition_id}, status=HTTP.OK)
