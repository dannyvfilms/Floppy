"""Cheap change detection for clients that mirror the library (#1527).

``GET /media/?updated_since=`` returns the entries that changed. These two
endpoints cover what that cannot say: whether anything changed at all, and
which entries were deleted.
"""

from http import HTTPStatus as HTTP  # noqa: N814

from django.apps import apps
from django.db.models import Max
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.media_list_filters import MediaListFilterError, _Params, parse_since
from app.models import DeletedEntry, Item, Media

from .helpers import paginate_data, parse_limit_offset


def tracking_models():
    """Return the concrete tracking-row models that carry ``updated_at``."""
    return [
        model
        for model in apps.get_models()
        if issubclass(model, Media) and not model._meta.abstract
    ]


def last_activity(user):
    """Return the newest change to the user's library, or None for an empty one.

    Deletions count: removing an entry leaves no row to stamp, so the newest
    tombstone is folded in.
    """
    stamps = [
        model._base_manager.filter(user=user).aggregate(latest=Max("updated_at"))[
            "latest"
        ]
        for model in tracking_models()
    ]
    stamps.append(
        DeletedEntry.objects.filter(user=user).aggregate(latest=Max("deleted_at"))[
            "latest"
        ],
    )
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


class LibraryActivityView(drf_views.APIView):
    """One timestamp that moves whenever the library changes."""

    @extend_schema(
        operation_id="getLibraryActivity",
        responses={
            200: {
                "type": "object",
                "required": ["last_activity"],
                "properties": {
                    "last_activity": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True,
                        "description": (
                            "Newest `updated_at` across the account's entries, "
                            "or the newest deletion if later; null for an empty "
                            "library. If it equals the value from the last sync, "
                            "nothing changed and the media list need not be read."
                        ),
                    },
                },
            },
        },
    )
    def get(self, request):
        """Return the account's last-activity timestamp."""
        stamp = last_activity(request.user)
        return Response({"last_activity": stamp.isoformat() if stamp else None})


class LibraryDeletedView(drf_views.APIView):
    """Entries the user deleted since a moment."""

    @extend_schema(
        operation_id="listDeletedMedia",
        parameters=[
            OpenApiParameter(
                name="deleted_since",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "ISO 8601 date or datetime; only deletions at or after it. "
                    "Omit for every recorded deletion."
                ),
            ),
            OpenApiParameter("limit", int),
            OpenApiParameter("offset", int),
        ],
        responses={200: {"type": "object"}},
    )
    def get(self, request):
        """List tombstones for deleted entries, oldest first.

        An entry is reported only while the user has no tracking row left for
        it, so deleting one of several plays does not read as deleting the show.
        """
        limit, offset, error_response = parse_limit_offset(request)
        if error_response:
            return error_response
        params = _Params(request, strict=True)
        try:
            since = parse_since(params, "deleted_since")
        except MediaListFilterError as error:
            return Response(
                {"detail": f"Invalid {error.parameter}: {error}"},
                status=HTTP.BAD_REQUEST,
            )
        tombstones = DeletedEntry.objects.filter(user=request.user)
        if since:
            tombstones = tombstones.filter(deleted_at__gte=since)
        tombstones = tombstones.order_by("deleted_at", "pk")
        live = _still_tracked(request.user, tombstones)
        rows = [
            {
                "media_type": row.media_type,
                "source": row.source,
                "media_id": row.media_id,
                "season_number": row.season_number,
                "deleted_at": row.deleted_at,
            }
            for row in tombstones
            if _key(row) not in live
        ]
        return Response(paginate_data(request, rows, limit, offset))


def _key(row):
    return (row.media_type, row.source, row.media_id, row.season_number)


def _still_tracked(user, tombstones):
    """Return the tombstone keys the user tracks again."""
    keys = {_key(row) for row in tombstones}
    if not keys:
        return set()
    items = Item.objects.filter(
        media_id__in={key[2] for key in keys},
    ).values_list("pk", "media_type", "source", "media_id", "season_number")
    key_by_item = {row[0]: row[1:] for row in items if row[1:] in keys}
    tracked = set()
    for model in tracking_models():
        for item_id in model._base_manager.filter(
            user=user,
            item_id__in=list(key_by_item),
        ).values_list("item_id", flat=True):
            tracked.add(key_by_item[item_id])
    return tracked
