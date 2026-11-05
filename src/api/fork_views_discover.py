# FORK: discover, home, and collection-parity endpoints mirroring the web
# views. URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814
from types import SimpleNamespace

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from app.discover import tab_cache as discover_tab_cache
from app.discover_views import (
    _discover_hidden_entries,
    _discover_response_rows,
    _invalidate_discover_after_action,
    _resolve_discover_media_type_for_user,
)
from app.helpers import build_provider_ids, is_item_collected
from app.home_artwork import refresh_home_artwork
from app.home_presentation import home_screen_payload, row_presentation
from app.models import (
    CollectionEntry,
    DiscoverFeedback,
    DiscoverFeedbackType,
    Item,
    MediaTypes,
    Sources,
)
from app.providers import services
from users.home_screen import (
    HomeScreenValidationError,
    build_home_page_groups,
    build_home_row,
    toggle_home_row_direction,
)

from .contract_serializers import (
    DetailErrorSerializer,
    RecommendationsEnvelopeSerializer,
)
from .helpers import paginate_data, parse_limit_offset
from .serializers import serialize_data

logger = logging.getLogger(__name__)


# /api/v1/collection/status/[item_id]/
class CollectionStatusView(drf_views.APIView):
    """Report whether an item has a collection entry (mirrors the web API)."""

    def get(self, request, item_id):
        """Return has_collection_data for the item."""
        item = Item.objects.filter(id=item_id).first()
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
        collection_entry = is_item_collected(request.user, item)
        return Response(
            {
                "item_id": int(item_id),
                "has_collection_data": collection_entry is not None,
            },
            status=HTTP.OK,
        )


# /api/v1/collection/seasons/[season_item_id]/
class CollectionSeasonView(drf_views.APIView):
    """Remove Sonarr-backed collected episode rows for a season."""

    def delete(self, request, season_item_id):
        """Delete the season's collected episode entries (mirrors web view)."""
        season_item = Item.objects.filter(
            id=season_item_id,
            media_type=MediaTypes.SEASON.value,
        ).first()
        if season_item is None:
            return Response(
                {"detail": "Season item not found."},
                status=HTTP.NOT_FOUND,
            )
        deleted_count, _ = CollectionEntry.objects.filter(
            user=request.user,
            item__media_id=season_item.media_id,
            item__source=season_item.source,
            item__media_type=MediaTypes.EPISODE.value,
            item__season_number=season_item.season_number,
            item__source_states__user=request.user,
            item__source_states__source="sonarr",
        ).delete()
        if not deleted_count:
            return Response(
                {"detail": "No collected episodes found for this season."},
                status=HTTP.NOT_FOUND,
            )
        return Response({"deleted": deleted_count}, status=HTTP.OK)


class DiscoverOffError(NotFound):
    """Raised when the account turned Discover off."""

    default_detail = "Discover is turned off for this account."


class DiscoverEnabledMixin:
    """404 the Discover endpoints for users who turned Discover off."""

    def initial(self, request, *args, **kwargs):
        """Reject the request after authentication when Discover is off."""
        super().initial(request, *args, **kwargs)
        if not request.user.show_discover:
            raise DiscoverOffError


# /api/v1/discover/
class DiscoverRowsView(DiscoverEnabledMixin, drf_views.APIView):
    """Discover rows for a media type (mirrors the web Discover page data)."""

    def get(self, request):
        """Return the cached Discover rows for the media type."""
        media_type = _resolve_discover_media_type_for_user(
            request.user,
            request.GET.get("media_type"),
        )
        show_more = request.GET.get("show_more") in {"1", "true", "True"}
        rows = _discover_response_rows(
            request.user,
            selected_media_type=media_type,
            show_more=show_more,
            discover_debug=False,
        )
        return Response(
            {
                "media_type": media_type,
                "show_more": show_more,
                "rows": [row.to_dict() for row in rows],
            },
            status=HTTP.OK,
        )


RECOMMENDATION_MEDIA_TYPES = {MediaTypes.MOVIE.value, MediaTypes.TV.value}
RECOMMENDATION_ROW_KEY = "top_picks_for_you"


def _recommendation_ids(candidate):
    """Return the `ids` map for one recommendation: stored ids, else provider."""
    item = Item.objects.filter(
        media_id=candidate["media_id"],
        source=candidate["source"],
        media_type=candidate["media_type"],
    ).first()
    ids = build_provider_ids(item)
    if not ids:
        try:
            metadata = services.get_media_metadata(
                candidate["media_type"],
                candidate["media_id"],
                candidate["source"],
            )
        except services.ProviderAPIError:
            logger.warning(
                "recommendation_ids_unavailable media_type=%s source=%s media_id=%s",
                candidate["media_type"],
                candidate["source"],
                candidate["media_id"],
            )
            metadata = {}
        ids = build_provider_ids(
            SimpleNamespace(
                provider_external_ids=metadata.get("provider_external_ids"),
            ),
        )
    if candidate["source"] in {Sources.TMDB.value, Sources.TVDB.value}:
        ids.setdefault(candidate["source"], str(candidate["media_id"]))
    return ids


# /api/v1/recommendations/
class RecommendationsView(DiscoverEnabledMixin, drf_views.APIView):
    """Personalized "Top Picks For You" as a flat list with provider ids.

    For external clients (for example a media-server plugin) that build their
    own libraries from IMDb/TMDB/TVDB ids rather than Floppy's item ids. Picks
    are the Discover row, so they follow its cache and refresh rules. Movie
    picks are the Planning list plus new titles matching the user's taste,
    never completed, dropped or in-progress ones. TV picks are the Planning
    list, ranked.
    """

    @extend_schema(
        operation_id="listRecommendations",
        parameters=[
            OpenApiParameter(
                name="media_type",
                type=str,
                location=OpenApiParameter.QUERY,
                enum=sorted(RECOMMENDATION_MEDIA_TYPES),
                description="`movie` (default) or `tv`.",
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Maximum picks; defaults to 20.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Zero-based offset; defaults to 0.",
            ),
        ],
        responses={
            200: RecommendationsEnvelopeSerializer,
            400: DetailErrorSerializer,
            404: DetailErrorSerializer,
        },
    )
    def get(self, request):
        """Return recommended titles for `media_type` (movie or tv)."""
        media_type = request.GET.get("media_type") or MediaTypes.MOVIE.value
        if media_type not in RECOMMENDATION_MEDIA_TYPES:
            return Response(
                {"detail": "media_type must be 'movie' or 'tv'."},
                status=HTTP.BAD_REQUEST,
            )
        limit, offset, err = parse_limit_offset(request)
        if err:
            return err
        rows = _discover_response_rows(
            request.user,
            selected_media_type=media_type,
            show_more=False,
            discover_debug=False,
        )
        row = next((r for r in rows if r.key == RECOMMENDATION_ROW_KEY), None)
        picks = [
            {
                "media_type": media_type,
                "source": item.source,
                "media_id": str(item.media_id),
                "title": item.title,
                "release_date": item.release_date,
                "genres": list(item.genres),
                "rating": item.rating,
                "image": item.image,
            }
            for item in (row.items if row else [])
        ]
        payload = paginate_data(request, picks, limit, offset)
        for pick in payload["results"]:
            pick["ids"] = _recommendation_ids(pick)
        return Response(payload, status=HTTP.OK)


# /api/v1/discover/refresh/
class DiscoverRefreshView(DiscoverEnabledMixin, drf_views.APIView):
    """Invalidate and queue a Discover refresh (mirrors refresh_discover)."""

    def post(self, request):
        """Queue a background rebuild for the media type's Discover tab."""
        media_type = _resolve_discover_media_type_for_user(
            request.user,
            request.data.get("media_type"),
        )
        show_more = bool(request.data.get("show_more"))
        discover_tab_cache.mark_active(
            request.user.id,
            media_type,
            show_more=show_more,
        )
        discover_tab_cache.bump_activity_version(request.user.id, media_type)
        discover_tab_cache.clear_row_cache(request.user.id, media_type)
        discover_tab_cache.schedule_tab_refresh(
            request.user.id,
            media_type,
            show_more=show_more,
            debounce_seconds=(
                discover_tab_cache.DISCOVER_PRIORITY_REFRESH_DEBOUNCE_SECONDS
            ),
            countdown=discover_tab_cache.DISCOVER_PRIORITY_REFRESH_COUNTDOWN,
            force=True,
            clear_provider_cache=True,
        )
        return Response(
            {"media_type": media_type, "show_more": show_more},
            status=HTTP.ACCEPTED,
        )


# /api/v1/discover/hidden/
class DiscoverHiddenView(DiscoverEnabledMixin, drf_views.APIView):
    """List or toggle items hidden from Discover."""

    def get(self, request):
        """Return the user's hidden Discover entries."""
        entries = _discover_hidden_entries(request.user)
        return Response(
            {
                "results": [
                    {
                        "item_id": entry.item_id,
                        "title": entry.item.title,
                        "media_type": entry.item.media_type,
                        "hidden_at": entry.updated_at,
                    }
                    for entry in entries
                ],
            },
            status=HTTP.OK,
        )

    def post(self, request):
        """Hide or unhide an item (mirrors discover_toggle_hidden)."""
        action = request.data.get("action")
        if action not in ("hide", "unhide"):
            return Response(
                {"detail": "action must be 'hide' or 'unhide'."},
                status=HTTP.BAD_REQUEST,
            )
        item = Item.objects.filter(id=request.data.get("item_id")).first()
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)

        if action == "hide":
            DiscoverFeedback.objects.update_or_create(
                user=request.user,
                item=item,
                feedback_type=DiscoverFeedbackType.NOT_INTERESTED.value,
                defaults={"source_context": "api"},
            )
        else:
            DiscoverFeedback.objects.filter(
                user=request.user,
                item=item,
                feedback_type=DiscoverFeedbackType.NOT_INTERESTED.value,
            ).delete()

        _invalidate_discover_after_action(
            request.user.id,
            item.library_media_type or item.media_type,
            discover_debug=False,
            feedback_change=True,
        )
        return Response(
            {"item_id": item.id, "hidden": action == "hide"},
            status=HTTP.OK,
        )


# /api/v1/home/
class HomeView(drf_views.APIView):
    """The user's home rows — the same groups the web home page renders."""

    def get(self, request):
        """Return home groups with serialized row items."""
        try:
            items_limit = max(1, min(int(request.GET.get("limit", 14)), 50))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid limit parameter"},
                status=HTTP.BAD_REQUEST,
            )
        if request.GET.get("presentation") in {"1", "true"}:
            http_request = getattr(request, "_request", request)
            deferred = request.GET.get("deferred") in {"1", "true"}
            return Response(
                home_screen_payload(
                    request.user,
                    http_request,
                    items_limit,
                    deferred=deferred,
                ),
                status=HTTP.OK,
            )
        groups = build_home_page_groups(request.user, items_limit)
        payload = []
        for group in groups:
            rows = []
            for row in group["rows"]:
                items = []
                for entry in row.get("items", []):
                    try:
                        items.append(serialize_data(entry))
                    except Exception:
                        logger.exception("Failed to serialize home row entry")
                        title = getattr(
                            getattr(entry, "item", None),
                            "title",
                            None,
                        ) or getattr(entry, "title", None)
                        items.append({"title": title})
                rows.append(
                    {
                        "row_id": row.get("row_id"),
                        "title": row.get("title"),
                        "summary": row.get("summary"),
                        "total": row.get("total"),
                        "items": items,
                    },
                )
            payload.append(
                {
                    "media_type": group["media_type"],
                    "label": group["label"],
                    "rows": rows,
                },
            )
        return Response({"groups": payload}, status=HTTP.OK)

# /api/v1/home/row/[row_id]/
class HomeRowView(drf_views.APIView):
    """One Home shelf window, for deferred rows and bounded load-more."""

    def get(self, request, row_id):
        """Return one bounded Home row window."""
        try:
            items_limit = max(1, min(int(request.GET.get("limit", 14)), 50))
            offset = max(int(request.GET.get("offset", "0")), 0)
            raw_seed = request.GET.get("seed", "")
            seed = int(raw_seed) if raw_seed not in (None, "") else 0
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid row window"},
                status=HTTP.BAD_REQUEST,
            )
        if offset:
            groups = build_home_page_groups(
                request.user,
                items_limit,
                load_row_id=row_id,
                load_row_offset=offset,
                load_row_seed=seed,
                append_only=True,
                only_row_id=row_id,
            )
            row = next(
                (
                    row
                    for group in groups
                    for row in group["rows"]
                    if row["row_id"] == row_id
                ),
                None,
            )
        else:
            row = build_home_row(request.user, row_id, items_limit)
        if row is None:
            return Response({"row": None}, status=HTTP.OK)
        http_request = getattr(request, "_request", request)
        return Response(
            {"row": row_presentation(row, request.user, http_request)},
            status=HTTP.OK,
        )


# /api/v1/home/rows/[row_id]/sort/
class HomeRowDirectionView(drf_views.APIView):
    """Flip one configured Home row's sort direction."""

    def post(self, request, row_id):
        """Flip the row's persisted sort direction and return it."""
        try:
            toggle_home_row_direction(request.user, row_id)
        except HomeScreenValidationError:
            return Response(
                {"detail": "Home row not found."},
                status=HTTP.NOT_FOUND,
            )
        row = build_home_row(request.user, row_id, 14, refresh=True)
        if row is None:
            return Response({"row": None}, status=HTTP.OK)
        http_request = getattr(request, "_request", request)
        return Response(
            {"row": row_presentation(row, request.user, http_request)},
            status=HTTP.OK,
        )


# /api/v1/home/artwork/
class HomeArtworkView(drf_views.APIView):
    """Refresh every Home row that still needs cover artwork in one request."""

    def get(self, request):
        """Refresh the polled rows together and report rows still missing art."""
        raw_ids = request.GET.get("ids", "")
        row_ids = {int(part) for part in raw_ids.split(",") if part.strip().isdigit()}
        raw_pending = request.GET.get("pending", "")
        rows_pending = raw_pending.isdigit() and int(raw_pending) > 0
        rows, poll_row_ids, pending = refresh_home_artwork(
            request.user,
            row_ids,
            rows_pending,
        )
        http_request = getattr(request, "_request", request)
        return Response(
            {
                "rows": [
                    row_presentation(row, request.user, http_request) for row in rows
                ],
                "pollRowIds": [str(row_id) for row_id in poll_row_ids],
                "pending": pending,
            },
            status=HTTP.OK,
        )
