# FORK: endpoints for fork-only features, kept out of the upstream-owned
# views.py so future feat/add-api syncs stay clean. URL wiring lives in
# fork_urls.py (included from urls.py with a single line).
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.db import IntegrityError, transaction
from django.db.models import prefetch_related_objects
from django_celery_results.models import TaskResult
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.forms import CollectionEntryForm
from app.models import (
    BasicMedia,
    CollectionEntry,
    CollectionEntrySource,
    Item,
    MediaTypes,
)

from .contract_serializers import DetailErrorSerializer
from .fork_helpers import get_or_create_provider_item
from .fork_serializers import CollectionEntrySerializer
from .helpers import (
    check_source_type,
    check_valid_type,
    paginate_data,
    parse_limit_offset,
    resolve_item_queryset,
)
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


# /api/v1/media/[media_type]/[source]/[media_id]/collection/
# /api/v1/media/tv/[source]/[media_id]/[season_number]/episodes/[episode_number]/collection/
class MediaCollectionView(drf_views.APIView):
    """Mark a title as owned, addressed by provider id instead of item id.

    Mirrors the web UI's collection_quick_add for clients (a downloader, a
    media server script) that know a TMDB/TVDB id but not Floppy's item id.
    Shows are collected per episode, so `tv` is accepted on the episode route
    only.

    Entries created here carry a ``CollectionEntrySource`` link (the same
    provenance record the importers use), so ``DELETE`` removes only what the
    API created and leaves copies added by hand. The link's uniqueness also
    settles two simultaneous first calls: the loser rolls back and reuses the
    winner's entry.
    """

    _SOURCE = "api"
    _RESOLUTION_MAX_LENGTH = CollectionEntry._meta.get_field("resolution").max_length

    def _identity(self, media_type, source, season_number, episode_number):
        """Return ``(lookup_media_type, error_response)`` for the route."""
        if episode_number is not None:
            if media_type != MediaTypes.TV.value:
                return None, Response(
                    {"detail": "Episodes are supported only for 'tv' media type."},
                    status=HTTP.BAD_REQUEST,
                )
            lookup_media_type = MediaTypes.EPISODE.value
        elif not check_valid_type(media_type):
            return None, Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )
        elif media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            return None, Response(
                {"detail": "Shows are collected per episode. Use the episode route."},
                status=HTTP.BAD_REQUEST,
            )
        else:
            lookup_media_type = media_type

        if not check_source_type(media_type, source):
            return None, Response(
                {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
                status=HTTP.BAD_REQUEST,
            )
        return lookup_media_type, None

    def _api_entries(self, user, item):
        """Return the user's copies of the item that this API created."""
        return CollectionEntry.objects.filter(
            user=user,
            item=item,
            source_records__source=self._SOURCE,
        )

    def _create_entry(self, user, item, resolution):
        """Return ``(entry, created)``, creating the API-owned copy at most once."""
        record_id = ":".join(
            str(part)
            for part in (
                item.source,
                item.media_type,
                item.media_id,
                item.season_number,
                item.episode_number,
            )
        )
        try:
            with transaction.atomic():
                entry = CollectionEntry.objects.create(
                    user=user,
                    item=item,
                    resolution=resolution,
                )
                CollectionEntrySource.objects.create(
                    user=user,
                    source=self._SOURCE,
                    source_record_id=record_id,
                    entry=entry,
                )
        except IntegrityError:
            # A simultaneous call won the unique link; use its entry.
            link = (
                CollectionEntrySource.objects.select_related("entry")
                .filter(user=user, source=self._SOURCE, source_record_id=record_id)
                .first()
            )
            if link is None:
                raise
            return link.entry, False
        return entry, True

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiTypes.OBJECT,
            201: OpenApiTypes.OBJECT,
            400: DetailErrorSerializer,
            404: DetailErrorSerializer,
            502: DetailErrorSerializer,
        },
    )
    def put(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number=None,
        episode_number=None,
    ):
        """Add the title to the collection, creating the item when unknown.

        Idempotent: an existing entry is returned, not duplicated. Optional
        body field `resolution` (e.g. "1080p") is stored on the entry and
        replaces the stored value on a repeat call, so a quality upgrade
        updates the same entry.
        """
        season_number = int(season_number) if season_number is not None else None
        episode_number = int(episode_number) if episode_number is not None else None
        lookup_media_type, error = self._identity(
            media_type,
            source,
            season_number,
            episode_number,
        )
        if error:
            return error

        if not isinstance(request.data, dict):
            return Response(
                {"detail": "Request body must be a JSON object."},
                status=HTTP.BAD_REQUEST,
            )
        resolution = request.data.get("resolution") or ""
        if (
            not isinstance(resolution, str)
            or len(resolution) > self._RESOLUTION_MAX_LENGTH
        ):
            return Response(
                {"detail": "Invalid 'resolution'."},
                status=HTTP.BAD_REQUEST,
            )

        item, error = get_or_create_provider_item(
            lookup_media_type,
            source,
            media_id,
            user=request.user,
            season_number=season_number,
            episode_number=episode_number,
        )
        if error:
            return error

        entry = (
            self._api_entries(request.user, item).first()
            or CollectionEntry.objects.filter(user=request.user, item=item).first()
        )
        created = False
        if entry is None:
            entry, created = self._create_entry(request.user, item, resolution)
        if not created and resolution and entry.resolution != resolution:
            entry.resolution = resolution
            entry.save(update_fields=["resolution", "updated_at"])
        status = HTTP.CREATED if created else HTTP.OK

        return Response(
            serialize_data(entry, serializer_class=CollectionEntrySerializer),
            status=status,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "all",
                OpenApiTypes.BOOL,
                description="Also remove copies that were not created through the API.",
            ),
        ],
        responses={
            204: None,
            400: DetailErrorSerializer,
            404: DetailErrorSerializer,
        },
    )
    def delete(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number=None,
        episode_number=None,
    ):
        """Remove the copy this API created (``all=true`` removes every copy)."""
        season_number = int(season_number) if season_number is not None else None
        episode_number = int(episode_number) if episode_number is not None else None
        lookup_media_type, error = self._identity(
            media_type,
            source,
            season_number,
            episode_number,
        )
        if error:
            return error

        item = resolve_item_queryset(
            media_id,
            source,
            lookup_media_type,
            season_number=season_number,
            episode_number=episode_number,
        ).first()
        if item is None:
            return Response(
                {"detail": "Collection entry not found."},
                status=HTTP.NOT_FOUND,
            )
        copies = CollectionEntry.objects.filter(user=request.user, item=item)
        entries = copies
        if request.query_params.get("all", "").lower() not in {"1", "true"}:
            entries = self._api_entries(request.user, item)
        entry_ids = list(entries.values_list("id", flat=True))
        if not entry_ids:
            detail = "Collection entry not found."
            if copies.exists():
                detail = (
                    "No copy was created through the API. "
                    "Use all=true to remove copies added elsewhere."
                )
            return Response({"detail": detail}, status=HTTP.NOT_FOUND)
        CollectionEntry.objects.filter(id__in=entry_ids).delete()
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
