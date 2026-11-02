# FORK: endpoints for fork-only features, kept out of the upstream-owned
# views.py so future feat/add-api syncs stay clean. URL wiring lives in
# fork_urls.py (included from urls.py with a single line).
import logging
import unicodedata
from http import HTTPStatus as HTTP  # noqa: N814

from django.db import IntegrityError, transaction
from django.db.models import prefetch_related_objects
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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


def _format_key(value):
    """Return a comparison key for a collection format.

    Folds Unicode form and case and keeps only letters and digits, so
    "Blu-ray", "bluray" and "BLU RAY" match while "Blu-ray" and "DVD" don't.
    """
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in text if char.isalnum())


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
            already_sliced=True,
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
        collected_at = form.cleaned_data.get("collected_at")
        if collected_at:
            CollectionEntry.objects.filter(id=entry.id).update(
                collected_at=collected_at
            )
            entry.collected_at = collected_at
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

        # Start from the stored values: the form would clear a field the
        # request leaves out (is_3d, bitrate, purchase_price).
        form_data = {
            name: entry.serializable_value(name)
            for name in CollectionEntryForm.Meta.fields
        }
        form_data.update(request.data)
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
        collected_at = form.cleaned_data.get("collected_at")
        if collected_at:
            CollectionEntry.objects.filter(id=entry.id).update(
                collected_at=collected_at
            )
            entry.collected_at = collected_at
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
    _TEXT_FIELDS = ("media_type", "resolution", "hdr", "audio_codec", "audio_channels")
    _LIBRARY_PARAMETER = OpenApiParameter(
        "library_media_type",
        OpenApiTypes.STR,
        description=(
            "The show's library bucket, e.g. `anime`; episodes in the anime "
            "library are only found with it."
        ),
    )

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

    def _find_item(self, request, media_id, source, media_type, season_number, episode_number):
        """Return the addressed item in the requested library, else the default one.

        A PUT for a show Floppy doesn't have yet creates the episode in the
        default library even with ``library_media_type=anime``, so calls with
        the same parameter fall back there to find it. A watch in the anime
        library can add a second item there later, so the default item also
        wins when only it holds this API's copy.
        """
        library_media_type = request.query_params.get("library_media_type")

        def lookup(bucket):
            return resolve_item_queryset(
                media_id,
                source,
                media_type,
                season_number=season_number,
                episode_number=episode_number,
                library_media_type=bucket,
            ).first()

        item = lookup(library_media_type)
        if not library_media_type:
            return item
        default_item = lookup(None)
        if item is None or (
            default_item is not None
            and not self._api_entries(request.user, item).exists()
            and self._api_entries(request.user, default_item).exists()
        ):
            return default_item
        return item

    def _api_entries(self, user, item):
        """Return the user's copies of the item that this API created."""
        return CollectionEntry.objects.filter(
            user=user,
            item=item,
            source_records__source=self._SOURCE,
        )

    def _reusable_entry(self, user, item, media_type):
        """Return a copy added elsewhere that this call may update, or None.

        Without a sent ``media_type`` any copy is reused. With one, only a
        copy of the same format (see ``_format_key``) or one without a format
        is, so a PUT for a digital copy never rewrites a Blu-ray added by hand.
        """
        copies = CollectionEntry.objects.filter(user=user, item=item)
        if not media_type:
            return copies.first()
        wanted = _format_key(media_type)
        copies = list(copies)
        same_format = [c for c in copies if _format_key(c.media_type) == wanted]
        no_format = [c for c in copies if not _format_key(c.media_type)]
        return next(iter(same_format or no_format), None)

    def _entry_fields(self, data):
        """Return ``(fields, error_response)`` for the optional body fields.

        Only the fields that were sent are returned, so a repeat call keeps
        the stored value of everything it leaves out.
        """
        fields = {}
        for name in self._TEXT_FIELDS:
            value = data.get(name) or ""
            max_length = CollectionEntry._meta.get_field(name).max_length
            if not isinstance(value, str) or len(value) > max_length:
                return None, self._invalid(name)
            if value:
                fields[name] = value

        is_3d = data.get("is_3d")
        if is_3d is not None:
            if not isinstance(is_3d, bool):
                return None, self._invalid("is_3d")
            fields["is_3d"] = is_3d

        bitrate = data.get("bitrate")
        if bitrate is not None:
            if isinstance(bitrate, bool) or not isinstance(bitrate, int) or bitrate < 0:
                return None, self._invalid("bitrate")
            fields["bitrate"] = bitrate

        collected_at = data.get("collected_at")
        if collected_at:
            try:
                parsed = (
                    parse_datetime(collected_at)
                    if isinstance(collected_at, str)
                    else None
                )
            except ValueError:
                parsed = None
            if parsed is None:
                return None, self._invalid("collected_at")
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            fields["collected_at"] = parsed
        return fields, None

    def _invalid(self, name):
        """Return the 400 response for an invalid body field."""
        return Response(
            {"detail": f"Invalid '{name}'."},
            status=HTTP.BAD_REQUEST,
        )

    def _create_entry(self, user, item, fields):
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
                entry = CollectionEntry.objects.create(user=user, item=item, **fields)
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
        parameters=[_LIBRARY_PARAMETER],
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
        body fields `media_type`, `resolution`, `hdr`, `is_3d`, `audio_codec`,
        `audio_channels`, `bitrate` and `collected_at` are stored on the entry
        and replace the stored values on a repeat call, so a quality upgrade
        updates the same entry. Without an API-created copy, a copy added
        elsewhere is reused when its `media_type` is empty or matches the sent
        one (any copy when none is sent); otherwise a new copy is created.
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
        fields, error = self._entry_fields(request.data)
        if error:
            return error

        item = self._find_item(
            request,
            media_id,
            source,
            lookup_media_type,
            season_number,
            episode_number,
        )
        if item is None:
            item, error = get_or_create_provider_item(
                lookup_media_type,
                source,
                media_id,
                user=request.user,
                season_number=season_number,
                episode_number=episode_number,
                library_media_type=request.query_params.get("library_media_type"),
            )
            if error:
                return error

        entry = self._api_entries(request.user, item).first()
        if entry is None:
            entry = self._reusable_entry(request.user, item, fields.get("media_type"))
            if entry is not None and entry.media_type:
                # Same format: keep the copy's own spelling ("Blu-ray").
                fields.pop("media_type", None)
        created = False
        if entry is None:
            entry, created = self._create_entry(request.user, item, fields)
        # create() ignores collected_at (auto_now_add), so a new entry still
        # differs there and this save stores it.
        changed = [
            name for name, value in fields.items() if getattr(entry, name) != value
        ]
        if changed:
            for name in changed:
                setattr(entry, name, fields[name])
            entry.save(update_fields=[*changed, "updated_at"])
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
            _LIBRARY_PARAMETER,
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

        item = self._find_item(
            request,
            media_id,
            source,
            lookup_media_type,
            season_number,
            episode_number,
        )
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
