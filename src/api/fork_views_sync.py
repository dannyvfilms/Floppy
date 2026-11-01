"""Opt-in reliable synchronization over the existing state and change tables."""

from urllib.parse import urlencode

from django.core import signing
from django.db.models import Max, Min
from django.urls import reverse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import (
    BackfillReconcileState,
    Item,
    PlaybackProgress,
    ProgressChange,
    WatchState,
    WatchStateChange,
    WatchStateSequence,
)
from app.services.sync_lock import state_transaction
from app.tasks_watch_state import REPAIR_KEY, REPAIR_VERSION, backfill_watch_state
from integrations.models import SyncBinding
from integrations.state.checkpoints import record_applied_position

from .fork_views_playback import item_reference, show_item_map

ITEM_FIELDS = (
    "id",
    "media_id",
    "media_type",
    "source",
    "season_number",
    "episode_number",
    "provider_external_ids",
)
SALT = "floppy.sync.contract.2"
RESOURCES = {"watched": WatchStateChange, "progress": ProgressChange}
FLOORS = {"watched": "watched_cursor_floor", "progress": "progress_cursor_floor"}
SYNC_PARAMETERS = [
    OpenApiParameter(
        "context",
        str,
        description="Required with contract=2; use the opaque value returned by bootstrap.",
    ),
    OpenApiParameter("cursor", int),
    OpenApiParameter("limit", int),
    OpenApiParameter("contract", str, enum=["2"]),
]


ERROR_SCHEMA = {
    "type": "object",
    "required": ["code", "detail"],
    "properties": {"code": {"type": "string"}, "detail": {"type": "string"}},
}
FEED_ERROR_SCHEMA = {
    **ERROR_SCHEMA,
    "required": ["detail"],
    "description": "Legacy errors may contain detail only. contract=2 errors also include a recovery code.",
}
BOOTSTRAP_SCHEMA = {
    "type": "object",
    "required": ["contract", "context", "generation", "cursors", "feeds", "snapshots"],
    "properties": {
        "contract": {"type": "integer", "enum": [2]},
        "context": {"type": "string"},
        "generation": {"type": "string", "format": "uuid"},
        "cursors": {
            "type": "object",
            "properties": {
                resource: {"type": "integer", "minimum": 0} for resource in RESOURCES
            },
        },
        **{
            name: {
                "type": "object",
                "properties": {resource: {"type": "string"} for resource in RESOURCES},
            }
            for name in ("feeds", "snapshots")
        },
    },
}
STATE_SCHEMA = {
    "type": "object",
    "properties": {
        **{
            field: {"type": "integer", "nullable": True}
            for field in (
                "item_id",
                "sequence",
                "revision",
                "previous_revision",
                "play_count",
                "position_seconds",
                "duration_seconds",
                "season_number",
                "episode_number",
            )
        },
        **{
            field: {"type": "string", "nullable": True}
            for field in (
                "media_id",
                "source",
                "media_type",
                "kind",
                "origin_key",
                "origin_kind",
                "correlation_id",
            )
        },
        "watched": {"type": "boolean"},
        "completed": {"type": "boolean"},
        "watched_at": {"type": "string", "format": "date-time", "nullable": True},
        "ids": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}
FEED_SCHEMA = {
    "type": "object",
    "required": [
        "results",
        "next_cursor",
        "has_more",
        "oldest_sequence",
        "newest_sequence",
    ],
    "properties": {
        "results": {"type": "array", "items": STATE_SCHEMA},
        "has_more": {"type": "boolean"},
        **{
            field: {"type": "integer", "nullable": True}
            for field in (
                "next_cursor",
                "oldest_sequence",
                "newest_sequence",
                "high_water",
                "minimum_valid_cursor",
            )
        },
        "generation": {"type": "string", "format": "uuid"},
        "recording_enabled": {"type": "boolean"},
        "complete": {"type": "boolean"},
    },
}
SNAPSHOT_SCHEMA = {
    "type": "object",
    "required": ["results", "has_more", "after", "cursor", "resource"],
    "properties": {
        "results": {"type": "array", "items": STATE_SCHEMA},
        "has_more": {"type": "boolean"},
        "after": {"type": "string", "nullable": True},
        "cursor": {"type": "integer"},
        "resource": {"type": "string", "enum": list(RESOURCES)},
    },
}


class SyncError(APIException):
    """A machine-readable recovery instruction rather than an empty success."""

    def __init__(self, code, detail, *, status=409):
        """Return an explicit synchronization error code and HTTP status."""
        self.status_code = status
        self.detail = {"code": code, "detail": detail}


def integer(params, name, default, minimum=0, maximum=None):
    """Validate bounded request integers before any acknowledgement or query."""
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        raise SyncError(
            code="invalid_parameter", detail=f"{name} must be an integer.", status=400
        ) from None
    if value < minimum or (maximum is not None and value > maximum):
        raise SyncError(
            code="invalid_parameter", detail=f"{name} is out of range.", status=400
        )
    return value


def validate_context(request, row):
    """Signature checks do not replace authentication or current generation checks."""
    encoded = request.query_params.get("context")
    if not encoded:
        raise SyncError(
            code="sync_not_initialized",
            detail="Call POST /api/v1/sync/bootstrap/ first.",
        )
    try:
        context = signing.loads(encoded, salt=SALT)
        valid = (
            isinstance(context, dict)
            and context["user"] == request.user.pk
            and type(context["sequence"]) is int
            and context["sequence"] >= 0
            and type(context["ceiling"]) is int
            and context["ceiling"] >= 0
        )
        generation = context["generation"]
    except (signing.BadSignature, KeyError, TypeError):
        valid = False
    if not valid:
        raise SyncError(
            code="invalid_context",
            detail="Invalid synchronization context.",
            status=400,
        )
    if generation != str(row.sync_generation):
        raise SyncError(
            code="sync_reset_required",
            detail="Synchronization was reset. Bootstrap again.",
        )
    if not row.api_feed_enabled:
        raise SyncError(
            code="sync_not_initialized", detail="Bootstrap synchronization first."
        )
    return context


def validate_position(row, resource, cursor):
    """Preserve validity across empty logs without assuming dense sequences."""
    if cursor < getattr(row, FLOORS[resource]):
        raise SyncError(
            code="cursor_expired",
            detail="Complete history is unavailable. Bootstrap again.",
        )
    if cursor > row.last_sequence:
        raise SyncError(
            code="cursor_invalid",
            detail="Cursor exceeds server position. Bootstrap again.",
        )


def availability(user, resource):
    """Legacy metadata explicitly carries no completeness guarantee."""
    row = WatchStateSequence.objects.filter(user=user).first()
    return {
        "recording_enabled": bool(row and (row.api_feed_enabled or row.emit_changes)),
        "minimum_valid_cursor": getattr(
            row,
            "watched_pruned_through"
            if resource == "watched"
            else "progress_pruned_through",
        )
        if row
        else 0,
        "complete": False,
    }


def serialize_changes(changes, resource):
    """Keep the legacy row vocabulary while adding actionable strict identity."""
    show_map = show_item_map(
        [change.item for change in changes if change.item], minimal=True
    )
    results = []
    for change in changes:
        item = change.item
        result = {
            "sequence": change.sequence,
            "kind": change.kind,
            "media_id": item.media_id if item else None,
            "source": item.source if item else None,
            "media_type": item.media_type if item else None,
            "item_id": change.item_id,
            **(item_reference(item, show_map) if item else {}),
            "origin_key": change.origin_key,
            "correlation_id": str(change.correlation_id),
        }
        if resource == "watched":
            result.update(
                revision=change.revision,
                previous_revision=change.previous_revision,
                watched=change.watched,
                play_count=change.play_count,
                watched_at=change.watched_at,
                origin_kind=change.origin_kind,
            )
        else:
            result.update(
                position_seconds=change.position_seconds,
                duration_seconds=change.duration_seconds,
                completed=change.completed,
            )
        results.append(result)
    return results


def strict_feed(request, resource):
    """Hold the writer's commit barrier through validation and serialization."""
    if request.query_params.get("contract") != "2":
        raise SyncError(
            code="unsupported_contract",
            detail="Supported opt-in contract is 2.",
            status=400,
        )
    cursor = integer(request.query_params, "cursor", 0)
    limit = integer(request.query_params, "limit", 100, 1, 500)
    with state_transaction(request.user.pk) as row:
        context = validate_context(request, row)
        validate_position(row, resource, cursor)
        if cursor < context["sequence"]:
            raise SyncError(
                code="cursor_invalid", detail="Cursor precedes this bootstrap baseline."
            )
        high_water = row.last_sequence
        retained = RESOURCES[resource].objects.filter(
            user=request.user,
            sequence__gt=getattr(row, FLOORS[resource]),
            sequence__lte=high_water,
        )
        bounds = retained.aggregate(oldest=Min("sequence"), newest=Max("sequence"))
        changes = list(
            retained.filter(sequence__gt=cursor)
            .select_related("item")
            .defer("item__watch_providers")
            .order_by("sequence")[: limit + 1]
        )
        has_more = len(changes) > limit
        results = serialize_changes(changes[:limit], resource)
        origin = request.query_params.get("connection")
        if origin:
            binding = SyncBinding.objects.filter(
                user=request.user, origin_key=origin
            ).first()
            if binding and cursor > 0:
                record_applied_position(
                    binding,
                    cursor,
                    resource="watched_state" if resource == "watched" else resource,
                )
        return Response(
            {
                "results": results,
                "next_cursor": results[-1]["sequence"] if has_more else high_water,
                "has_more": has_more,
                "oldest_sequence": bounds["oldest"],
                "newest_sequence": bounds["newest"],
                "high_water": high_water,
                "minimum_valid_cursor": getattr(row, FLOORS[resource]),
                "recording_enabled": True,
                "complete": True,
                "generation": str(row.sync_generation),
            }
        )


class SyncBootstrapView(APIView):
    """Enable a durable feed without approving a provider connection."""

    @extend_schema(request=None, responses={200: BOOTSTRAP_SCHEMA, 409: ERROR_SCHEMA})
    def post(self, request):
        """Capture a committed baseline and enable durable recording."""
        # Existing repair is versioned and durable; Redis and worker restarts
        # cannot make an incomplete baseline look initialized.
        with state_transaction(request.user.pk) as row:
            ready = BackfillReconcileState.objects.filter(
                key=f"{REPAIR_KEY}_user_{request.user.pk}",
                strategy_version=REPAIR_VERSION,
                completed_at__isnull=False,
            ).exists()
            if ready:
                if not row.api_feed_enabled:
                    row.api_feed_enabled = True
                    row.last_sequence += 1
                    row.watched_cursor_floor = row.last_sequence
                    row.progress_cursor_floor = row.last_sequence
                    row.save(
                        update_fields=[
                            "api_feed_enabled",
                            "last_sequence",
                            "watched_cursor_floor",
                            "progress_cursor_floor",
                        ]
                    )
                ceiling = Item.objects.aggregate(value=Max("pk"))["value"] or 0
                context = signing.dumps(
                    {
                        "user": request.user.pk,
                        "generation": str(row.sync_generation),
                        "sequence": row.last_sequence,
                        "ceiling": ceiling,
                    },
                    salt=SALT,
                    compress=True,
                )
                feeds = {}
                snapshots = {}
                for resource in RESOURCES:
                    name = (
                        "api_sync_changes"
                        if resource == "watched"
                        else "api_sync_progress_changes"
                    )
                    feeds[resource] = (
                        reverse(name)
                        + "?"
                        + urlencode(
                            {
                                "contract": 2,
                                "context": context,
                                "cursor": row.last_sequence,
                            }
                        )
                    )
                    snapshots[resource] = (
                        reverse("api_sync_snapshot")
                        + "?"
                        + urlencode({"context": context, "resource": resource})
                    )
                return Response(
                    {
                        "contract": 2,
                        "context": context,
                        "generation": str(row.sync_generation),
                        "cursors": dict.fromkeys(RESOURCES, row.last_sequence),
                        "feeds": feeds,
                        "snapshots": snapshots,
                    }
                )
        backfill_watch_state.delay(user_id=request.user.pk, only_if_pending=True)
        raise SyncError(
            code="sync_initializing",
            detail="Canonical repair is pending. Retry bootstrap.",
        )


class SyncSnapshotView(APIView):
    """A bounded keyset baseline, followed by replay from the captured cursor."""

    @extend_schema(
        parameters=[
            OpenApiParameter("context", str, required=True),
            OpenApiParameter("resource", str, enum=list(RESOURCES), required=True),
            OpenApiParameter("after", str),
            OpenApiParameter("limit", int),
        ],
        responses={200: SNAPSHOT_SCHEMA, 400: ERROR_SCHEMA, 409: ERROR_SCHEMA},
    )
    def get(self, request):
        """Return one resumable page of current state."""
        resource = request.query_params.get("resource")
        if resource not in RESOURCES:
            raise SyncError(
                code="invalid_resource",
                detail="Choose watched or progress.",
                status=400,
            )
        limit = integer(request.query_params, "limit", 100, 1, 500)
        with state_transaction(request.user.pk) as row:
            context = validate_context(request, row)
            validate_position(row, resource, context["sequence"])
            after = 0
            if request.query_params.get("after"):
                try:
                    page = signing.loads(
                        request.query_params["after"], salt=SALT + ".page"
                    )
                    if (
                        page["context"] != request.query_params["context"]
                        or page["resource"] != resource
                    ):
                        raise ValueError  # noqa: TRY301
                    after = page["item"]
                    if type(after) is not int or after < 0:
                        raise ValueError  # noqa: TRY301
                except (signing.BadSignature, KeyError, TypeError, ValueError):
                    raise SyncError(
                        code="invalid_page",
                        detail="Invalid snapshot continuation.",
                        status=400,
                    ) from None
            model = WatchState if resource == "watched" else PlaybackProgress
            state_fields = (
                ("watched", "play_count", "last_watched_at", "revision")
                if resource == "watched"
                else ("position_seconds", "duration_seconds", "completed")
            )
            rows = list(
                model.objects.filter(
                    user=request.user,
                    item_id__gt=after,
                    item_id__lte=context["ceiling"],
                )
                .select_related("item")
                .only(
                    "item", *state_fields, *(f"item__{field}" for field in ITEM_FIELDS)
                )
                .order_by("item_id")[: limit + 1]
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            show_map = show_item_map([state.item for state in rows], minimal=True)
            results = []
            for state in rows:
                item = state.item
                result = {
                    "item_id": item.pk,
                    "media_id": item.media_id,
                    "source": item.source,
                    "media_type": item.media_type,
                    **item_reference(item, show_map),
                }
                if resource == "watched":
                    result.update(
                        watched=state.watched,
                        play_count=state.play_count,
                        watched_at=state.last_watched_at,
                        revision=state.revision,
                    )
                else:
                    result.update(
                        position_seconds=state.position_seconds,
                        duration_seconds=state.duration_seconds,
                        completed=state.completed,
                    )
                results.append(result)
            after_token = (
                signing.dumps(
                    {
                        "context": request.query_params["context"],
                        "resource": resource,
                        "item": rows[-1].item_id,
                    },
                    salt=SALT + ".page",
                    compress=True,
                )
                if has_more
                else None
            )
            return Response(
                {
                    "results": results,
                    "has_more": has_more,
                    "after": after_token,
                    "cursor": context["sequence"],
                    "resource": resource,
                }
            )
