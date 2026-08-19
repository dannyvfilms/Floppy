# FORK: discover, home, and collection-parity endpoints mirroring the web
# views. URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from rest_framework import views as drf_views
from rest_framework.response import Response

from app.discover import tab_cache as discover_tab_cache
from app.discover_views import (
    _discover_hidden_entries,
    _discover_response_rows,
    _invalidate_discover_after_action,
    _resolve_discover_media_type_for_user,
)
from app.helpers import is_item_collected
from app.models import (
    CollectionEntry,
    DiscoverFeedback,
    DiscoverFeedbackType,
    Item,
    MediaTypes,
)
from users.home_screen import build_home_page_groups

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


# /api/v1/discover/
class DiscoverRowsView(drf_views.APIView):
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


# /api/v1/discover/refresh/
class DiscoverRefreshView(drf_views.APIView):
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
class DiscoverHiddenView(drf_views.APIView):
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
