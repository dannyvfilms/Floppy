# FORK: endpoints for fork-only features, kept out of the upstream-owned
# views.py so future feat/add-api syncs stay clean. URL wiring lives in
# fork_urls.py (included from urls.py with a single line).
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.db.models import prefetch_related_objects
from django_celery_results.models import TaskResult
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.forms import CollectionEntryForm
from app.models import BasicMedia, CollectionEntry, Item, MediaTypes

from .fork_serializers import CollectionEntrySerializer
from .helpers import paginate_data, parse_limit_offset
from .serializers import serialize_data

logger = logging.getLogger(__name__)


def _resolve_user_media(user, media_id, media_type, source, season_number=None):
    """Return the user's tracked media row for the identifiers, or None."""
    queryset = BasicMedia.objects.filter_media_prefetch(
        user,
        media_id,
        media_type,
        source,
        season_number=season_number,
    )
    results = list(queryset[:1])
    return results[0] if results else None


# /api/v1/media/[media_type]/[source]/[media_id]/progress/
# /api/v1/media/[media_type]/[source]/[media_id]/[season_number]/progress/
class MediaProgressView(drf_views.APIView):
    """Increase or decrease progress on a tracked media item.

    Mirrors the web UI's progress changer (app/views.py progress_edit):
    seasons advance/rewind their next episode, other types adjust the
    progress counter with the same model-level semantics.
    """

    def post(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number=None,
    ):
        """Apply an increase/decrease operation to the tracked media."""
        operation = request.data.get("operation")
        if operation not in ("increase", "decrease"):
            return Response(
                {"detail": "'operation' must be 'increase' or 'decrease'."},
                status=HTTP.BAD_REQUEST,
            )

        lookup_media_type = (
            MediaTypes.SEASON.value if season_number is not None else media_type
        )
        media = _resolve_user_media(
            request.user,
            media_id,
            lookup_media_type,
            source,
            season_number=season_number,
        )
        if media is None:
            return Response(
                {"detail": "Media not found."},
                status=HTTP.NOT_FOUND,
            )

        if operation == "increase":
            media.increase_progress()
        else:
            media.decrease_progress()

        if lookup_media_type == MediaTypes.SEASON.value:
            # clear prefetch cache to get the updated episodes
            media.refresh_from_db()
            prefetch_related_objects([media], "episodes")

        return Response(serialize_data(media), status=HTTP.OK)


# /api/v1/collection/
class CollectionView(drf_views.APIView):
    """List collection entries or add an owned copy to the collection."""

    def get(self, request):
        """List the user's collection entries."""
        limit, offset, error_response = parse_limit_offset(request)
        if error_response is not None:
            return error_response

        queryset = (
            CollectionEntry.objects.filter(user=request.user)
            .select_related("item")
            .order_by("-collected_at", "-id")
        )
        item_media_type = request.query_params.get("item_media_type")
        if item_media_type:
            queryset = queryset.filter(item__media_type=item_media_type)

        total = queryset.count()
        paginated = paginate_data(
            request,
            list(queryset[offset : offset + limit]),
            limit,
            offset,
            total=total,
        )
        paginated["results"] = serialize_data(
            paginated["results"],
            many=True,
            serializer_class=CollectionEntrySerializer,
        )
        return Response(paginated, status=HTTP.OK)

    def post(self, request):
        """Add an item to the collection (mirrors collection_add)."""
        item_id = request.data.get("item_id")
        if not item_id:
            return Response(
                {"detail": "'item_id' is required."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            item = Item.objects.get(id=item_id)
        except Item.DoesNotExist:
            return Response(
                {"detail": "Item not found."},
                status=HTTP.NOT_FOUND,
            )

        form_data = dict(request.data)
        form_data["item"] = item.id
        form = CollectionEntryForm(
            form_data,
            user=request.user,
            collection_media_type=item.media_type,
        )
        if not form.is_valid():
            return Response(
                {"detail": "Invalid collection data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )

        entry = form.save(commit=False)
        entry.user = request.user
        entry.item = item
        entry.save()
        return Response(
            serialize_data(entry, serializer_class=CollectionEntrySerializer),
            status=HTTP.CREATED,
        )


# /api/v1/collection/[entry_id]/
class CollectionEntryView(drf_views.APIView):
    """Retrieve, update, or remove a single collection entry."""

    def _get_entry(self, request, entry_id):
        try:
            return CollectionEntry.objects.select_related("item").get(
                id=entry_id,
                user=request.user,
            )
        except CollectionEntry.DoesNotExist:
            return None

    def get(self, request, entry_id):
        """Return a single collection entry."""
        entry = self._get_entry(request, entry_id)
        if entry is None:
            return Response(
                {"detail": "Collection entry not found."},
                status=HTTP.NOT_FOUND,
            )
        return Response(
            serialize_data(entry, serializer_class=CollectionEntrySerializer),
            status=HTTP.OK,
        )

    def patch(self, request, entry_id):
        """Update collection entry metadata (mirrors collection_update)."""
        entry = self._get_entry(request, entry_id)
        if entry is None:
            return Response(
                {"detail": "Collection entry not found."},
                status=HTTP.NOT_FOUND,
            )

        form_data = dict(request.data)
        form_data.setdefault("item", entry.item_id)
        form = CollectionEntryForm(
            form_data,
            instance=entry,
            user=request.user,
            collection_media_type=entry.item.media_type,
        )
        if not form.is_valid():
            return Response(
                {"detail": "Invalid collection data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )

        entry = form.save()
        return Response(
            serialize_data(entry, serializer_class=CollectionEntrySerializer),
            status=HTTP.OK,
        )

    def delete(self, request, entry_id):
        """Remove an entry from the collection (mirrors collection_remove)."""
        entry = self._get_entry(request, entry_id)
        if entry is None:
            return Response(
                {"detail": "Collection entry not found."},
                status=HTTP.NOT_FOUND,
            )
        entry.delete()
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/tasks/[task_id]/
class TaskStatusView(drf_views.APIView):
    """Report the status of a Celery task dispatched by an API endpoint.

    Ownership is verified against the stored TaskResult's kwargs (the same
    user_id convention users.models uses for import activity); tasks that
    belong to other users 404. Tasks with no stored result yet report PENDING.
    """

    def get(self, request, task_id):
        """Return the current state of the task."""
        record = TaskResult.objects.filter(task_id=task_id).first()
        if record is None:
            # No stored result yet: either still queued or unknown. Celery
            # reports both as PENDING, which leaks nothing about other users.
            return Response(
                {"task_id": task_id, "status": "PENDING"},
                status=HTTP.OK,
            )

        kwargs_text = record.task_kwargs or ""
        owner_markers = (
            f"'user_id': {request.user.id},",
            f"'user_id': {request.user.id}}}",
            f'"user_id": {request.user.id},',
            f'"user_id": {request.user.id}}}',
        )
        if not any(marker in kwargs_text for marker in owner_markers):
            return Response(
                {"detail": "Task not found."},
                status=HTTP.NOT_FOUND,
            )

        return Response(
            {
                "task_id": task_id,
                "task_name": record.task_name,
                "status": record.status,
                "date_created": record.date_created,
                "date_done": record.date_done,
                "result": record.result,
            },
            status=HTTP.OK,
        )
