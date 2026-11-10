"""Authenticated native library preferences and saved views."""

import uuid
from http import HTTPStatus as HTTP  # noqa: N814

from django.core.cache import cache
from django.db import transaction
from django.http import QueryDict
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.collection_views import (
    _SEASON_OR_SHOW_MEDIA_TYPES,
    _expand_collection_entry_to_episodes,
)
from app.models import CollectionEntry, Item
from users.models import SavedView

MAX_SAVED_VIEW_QUERY_LENGTH = 4000
MAX_BULK_SHOWS = 1000
MAX_BULK_COLLECTION_ITEMS = 500


class SavedViewInputSerializer(serializers.Serializer):
    """Input for creating a native library saved view."""

    media_type = serializers.CharField()
    name = serializers.CharField(max_length=100)
    query = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class SavedViewOutputSerializer(serializers.Serializer):
    """Public saved view fields returned to the native library."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    media_type = serializers.CharField()
    query = serializers.CharField(allow_blank=True)
    position = serializers.IntegerField()


def _saved_view_data(view):
    return {
        "id": view.id,
        "name": view.name,
        "media_type": view.media_type,
        "query": view.query,
        "position": view.position,
    }


class LibrarySavedViewsView(drf_views.APIView):
    """List and create the authenticated user's saved media-list views."""

    @extend_schema(parameters=[OpenApiParameter("media_type", str)], responses=SavedViewOutputSerializer(many=True))
    def get(self, request):
        """Return the caller's saved views for a media type."""
        media_type = request.query_params.get("media_type", "")
        if media_type not in request.user.get_sidebar_media_types():
            return Response({"detail": "Invalid media type."}, status=HTTP.BAD_REQUEST)
        views = SavedView.objects.filter(user=request.user, media_type=media_type)
        return Response([_saved_view_data(view) for view in views], status=HTTP.OK)

    @extend_schema(request=SavedViewInputSerializer, responses={201: SavedViewOutputSerializer})
    def post(self, request):
        """Create a named, caller-owned media-list query."""
        media_type = str(request.data.get("media_type", ""))
        name = str(request.data.get("name", "")).strip()[:100]
        query = str(request.data.get("query", ""))
        if media_type not in request.user.get_sidebar_media_types():
            return Response({"detail": "Invalid media type."}, status=HTTP.BAD_REQUEST)
        if not name:
            return Response({"detail": "Give the view a name."}, status=HTTP.BAD_REQUEST)
        if len(query) > MAX_SAVED_VIEW_QUERY_LENGTH:
            return Response({"detail": "Saved view query is too long."}, status=HTTP.BAD_REQUEST)
        if request.user.is_demo:
            return Response({"detail": "This section is view-only for demo accounts."}, status=HTTP.FORBIDDEN)
        last = SavedView.objects.filter(user=request.user, media_type=media_type).order_by("-position").first()
        view = SavedView.objects.create(
            user=request.user,
            media_type=media_type,
            name=name,
            query=query,
            position=last.position + 1 if last else 0,
        )
        return Response(_saved_view_data(view), status=HTTP.CREATED)


class LibrarySavedViewDetailView(drf_views.APIView):
    """Read or delete one of the authenticated user's saved list views."""

    @extend_schema(responses=SavedViewOutputSerializer)
    def get(self, request, view_id):
        """Return one saved view only when it belongs to the caller."""
        view = SavedView.objects.filter(user=request.user, pk=view_id).first()
        if view is None:
            return Response({"detail": "Saved view not found."}, status=HTTP.NOT_FOUND)
        return Response(_saved_view_data(view), status=HTTP.OK)

    def delete(self, request, view_id):
        """Delete one saved view only when it belongs to the caller."""
        view = SavedView.objects.filter(user=request.user, pk=view_id).first()
        if view is None:
            return Response({"detail": "Saved view not found."}, status=HTTP.NOT_FOUND)
        if request.user.is_demo:
            return Response({"detail": "This section is view-only for demo accounts."}, status=HTTP.FORBIDDEN)
        view.delete()
        return Response(status=HTTP.NO_CONTENT)


class LibrarySavedViewsReorderView(drf_views.APIView):
    """Persist an ordered list of the caller's saved views for one media type."""

    @extend_schema(request={"application/json": {"type": "object", "properties": {
        "media_type": {"type": "string"}, "ids": {"type": "array", "items": {"type": "integer"}},
    }}}, responses={204: None})
    def post(self, request):
        """Save the submitted order for the caller's views of one media type."""
        media_type = str(request.data.get("media_type", ""))
        ids = request.data.get("ids", [])
        if media_type not in request.user.get_sidebar_media_types() or not isinstance(ids, list):
            return Response({"detail": "Invalid media type or view order."}, status=HTTP.BAD_REQUEST)
        if request.user.is_demo:
            return Response({"detail": "This section is view-only for demo accounts."}, status=HTTP.FORBIDDEN)
        with transaction.atomic():
            views = list(SavedView.objects.select_for_update().filter(user=request.user, media_type=media_type))
            by_id = {str(view.id): view for view in views}
            order = [str(value) for value in ids if str(value) in by_id]
            order.extend(key for key in by_id if key not in order)
            for position, key in enumerate(order):
                by_id[key].position = position
            SavedView.objects.bulk_update(by_id.values(), ["position"])
        return Response(status=HTTP.NO_CONTENT)


class LibraryBulkCollectionView(drf_views.APIView):
    """Quick-add selected Items to the caller's collection, idempotently."""

    @extend_schema(
        request={"application/json": {"type": "object", "required": ["item_ids"], "properties": {
            "item_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": MAX_BULK_COLLECTION_ITEMS},
        }}},
        responses={200: {"type": "object", "properties": {
            "created": {"type": "integer"}, "already_present": {"type": "integer"}, "skipped": {"type": "integer"},
        }}},
    )
    def post(self, request):
        """Add ordinary copies and expand shows/seasons with the web rules."""
        item_ids = request.data.get("item_ids")
        if not isinstance(item_ids, list) or not item_ids:
            return Response({"detail": "At least one item is required."}, status=HTTP.BAD_REQUEST)
        if len(item_ids) > MAX_BULK_COLLECTION_ITEMS or any(not str(value).isdigit() for value in item_ids):
            return Response({"detail": f"Select up to {MAX_BULK_COLLECTION_ITEMS} item ids."}, status=HTTP.BAD_REQUEST)

        ids = [int(value) for value in item_ids]
        items_by_id = Item.objects.in_bulk(ids)
        ordinary_items = [
            item for item_id, item in items_by_id.items()
            if item_id in ids and item.media_type not in _SEASON_OR_SHOW_MEDIA_TYPES
        ]
        result = {"created": 0, "already_present": 0, "skipped": len(ids) - len(items_by_id)}
        existing_ids = set(CollectionEntry.objects.filter(
            user=request.user, item_id__in=[item.id for item in ordinary_items],
        ).values_list("item_id", flat=True))
        to_create = [CollectionEntry(user=request.user, item=item)
            for item in ordinary_items if item.id not in existing_ids]
        if to_create:
            CollectionEntry.objects.bulk_create(to_create)
        result["created"] += len(to_create)
        result["already_present"] += len(ordinary_items) - len(to_create)

        for item_id in ids:
            item = items_by_id.get(item_id)
            if item is None or item.media_type not in _SEASON_OR_SHOW_MEDIA_TYPES:
                continue
            try:
                with transaction.atomic():
                    created_entries, skipped_count = _expand_collection_entry_to_episodes(
                        request.user, item, cleaned_data={},
                    )
            except Exception:
                result["skipped"] += 1
                continue
            result["created"] += len(created_entries)
            result["already_present"] += skipped_count
        return Response(result, status=HTTP.OK)


class LibraryBulkPlaysView(drf_views.APIView):
    """Preview or queue the web-equivalent Add Plays job for selected shows."""

    @extend_schema(
        request={"application/json": {"type": "object", "required": ["item_ids", "options"], "properties": {
            "item_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": MAX_BULK_SHOWS},
            "options": {"type": "object"}, "dry_run": {"type": "boolean"},
        }}},
        responses={202: {"type": "object", "properties": {"success": {"type": "boolean"}, "operation_id": {"type": "string"}}}},
    )
    def post(self, request):
        """Validate an owned set of show item ids and queue preview or apply."""
        from app.services import bulk_show_plays
        from app.tasks import bulk_show_plays_task

        item_ids = request.data.get("item_ids")
        if not isinstance(item_ids, list) or not item_ids:
            return Response({"detail": "'item_ids' must be a non-empty array."}, status=HTTP.BAD_REQUEST)
        if len(item_ids) > MAX_BULK_SHOWS or any(not str(value).isdigit() for value in item_ids):
            return Response({"detail": f"'item_ids' must contain at most {MAX_BULK_SHOWS} show ids."}, status=HTTP.BAD_REQUEST)
        options_data = QueryDict("", mutable=True)
        options_data.update(request.data.get("options") or {})
        options, error = bulk_show_plays.parse_options(options_data)
        if options is None:
            return Response({"detail": error}, status=HTTP.BAD_REQUEST)
        dry_run = request.data.get("dry_run") is True
        operation_id = uuid.uuid4().hex
        if not dry_run and not cache.add(
            bulk_show_plays.lock_key(request.user.id), operation_id, bulk_show_plays.LOCK_TTL,
        ):
            return Response({"detail": "Another history job is still running. Try again soon."}, status=HTTP.CONFLICT)
        cache.set(bulk_show_plays.status_key(request.user.id, operation_id), {
            "state": "running", "dry_run": dry_run, "total": len(item_ids), "done": 0,
        }, bulk_show_plays.STATUS_TTL)
        bulk_show_plays_task.delay(
            request.user.id, [int(value) for value in item_ids], options.as_task_kwargs(), operation_id, dry_run,
        )
        return Response({"success": True, "operation_id": operation_id}, status=HTTP.ACCEPTED)


class LibraryBulkPlaysStatusView(drf_views.APIView):
    """Read progress for an Add Plays operation owned by the caller."""

    @extend_schema(responses={200: {"type": "object"}})
    def get(self, request, operation_id):
        """Return only the caller's cached operation state."""
        from app.services import bulk_show_plays

        state = cache.get(bulk_show_plays.status_key(request.user.id, operation_id))
        if state is None:
            return Response({"detail": "This job has expired."}, status=HTTP.NOT_FOUND)
        return Response(state, status=HTTP.OK)
