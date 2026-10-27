# FORK: canonical watched-state endpoints for external synchronizing clients.
# Deliberately separate from the playback and history endpoints: setting
# unwatched is not deleting history, and the two must not share a route.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.db import transaction
from django.utils import timezone
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.models import (
    MediaTypes,
    WatchState,
    WatchStateOrigin,
    WatchStateSequence,
)
from app.services.progress_changes import (
    PROGRESS_RESOURCE,
    retained_progress_range,
)
from app.services.watch_state import (
    RevisionConflictError,
    changes_since,
    effective_state,
    record_state_change,
    retained_change_range,
)
from app.tasks_watch_state import watch_state_repair_complete
from integrations.models import (
    CAPABILITY_WATCHED_PULL,
    OutboundDeliveryStatus,
    StateConflict,
    StateConflictStatus,
    SyncBinding,
    SyncBindingStatus,
    SyncCheckpoint,
    SyncClientKind,
    SyncDirection,
)
from integrations.state.checkpoints import (
    WATCHED_STATE_RESOURCE,
    pin_snapshot_position,
    record_applied_position,
    reset_pull_positions,
)
from integrations.state.identity import activate_binding, get_or_create_binding

from .fork_views_playback import item_reference, show_item_map
from .helpers import check_source_type, check_valid_type, resolve_item_queryset

logger = logging.getLogger(__name__)

MAX_CHANGE_PAGE = 200
DEFAULT_SNAPSHOT_PAGE = 500
MAX_SNAPSHOT_PAGE = 1000
SNAPSHOT_MEDIA_TYPES = (MediaTypes.MOVIE.value, MediaTypes.EPISODE.value)
MAX_CONNECTION_FIELD = 255
# Every registration turns the account's change log on and is held against it
# until it checks in, so a runaway client or a leaked token must not be able to
# mint them without bound.
MAX_PULL_CONNECTIONS = 10
PROJECTION_RETRY_AFTER_SECONDS = 300

_INACTIVE_DETAIL = {
    "missing": "No such connection for this account. Register it again.",
    "not_pull": "This connection is not a pull-sync client.",
    "pending": "This connection has not been approved yet.",
    "disabled": "This connection was turned off by its owner.",
    "needs_reapproval": "This connection needs its owner to approve it again.",
    "kill_switch": "This connection is switched off by its owner.",
    "emission_off": (
        "Floppy is not recording changes for this account, so a cursor would "
        "describe a log nobody is writing."
    ),
}


def _integer_param(request, name, *, default, minimum):
    """Return (value, error) for an integer query parameter at least ``minimum``."""
    raw = request.query_params.get(name)
    if raw is None:
        return default, None
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or value < minimum:
        kind = "a positive" if minimum > 0 else "a non-negative"
        return None, Response(
            {"detail": f"{name} must be {kind} integer."},
            status=HTTP.BAD_REQUEST,
        )
    return value, None


def _inactive(reason):
    """Return the 409 that says why a connection cannot be served."""
    return Response(
        {
            "code": "connection_inactive",
            "reason": reason,
            "detail": _INACTIVE_DETAIL[reason],
        },
        status=HTTP.CONFLICT,
    )


def _cursor_expired(reason, detail):
    """Return the 409 that sends a pull client back to take a snapshot."""
    return Response(
        {"code": "cursor_expired", "reason": reason, "detail": detail},
        status=HTTP.CONFLICT,
    )


def _projection_incomplete_response():
    return Response(
        {
            "code": "projection_incomplete",
            "detail": (
                "Floppy is still rebuilding this account's watched state. "
                "Retry shortly."
            ),
        },
        status=HTTP.SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(PROJECTION_RETRY_AFTER_SECONDS)},
    )


def _pull_binding_problem(binding):
    """Return why ``binding`` cannot serve a pull client, or None if it can."""
    if binding is None:
        return "missing"
    if not binding.has_capability(CAPABILITY_WATCHED_PULL):
        return "not_pull"
    if binding.kill_switch:
        return "kill_switch"
    if binding.status == SyncBindingStatus.PENDING.value:
        return "pending"
    if binding.status == SyncBindingStatus.DISABLED.value:
        return "disabled"
    if binding.status == SyncBindingStatus.NEEDS_REAPPROVAL.value:
        return "needs_reapproval"
    if not WatchStateSequence.objects.filter(
        user_id=binding.user_id,
        emit_changes=True,
    ).exists():
        return "emission_off"
    return None


def _pinned_position(binding):
    """Return the position a snapshot pinned for this binding, if any."""
    return SyncCheckpoint.objects.filter(
        binding=binding,
        resource=WATCHED_STATE_RESOURCE,
    ).first()


def _serialize_state(state, item):
    """Return the public shape of one canonical state."""
    if state is None:
        return {
            "media_id": item.media_id,
            "source": item.source,
            "media_type": item.media_type,
            "watched": False,
            "play_count": 0,
            "first_watched_at": None,
            "last_watched_at": None,
            "revision": 0,
            "conflicted": False,
            "provenance": None,
        }

    return {
        "media_id": item.media_id,
        "source": item.source,
        "media_type": item.media_type,
        "watched": state.watched,
        "play_count": state.play_count,
        "first_watched_at": state.first_watched_at,
        "last_watched_at": state.last_watched_at,
        "revision": state.revision,
        "conflicted": state.conflicted,
        "provenance": {
            # Explicit and inferred manual changes stay distinguishable: a
            # client showing "you marked this watched" must not say so about a
            # state Floppy inferred from a reconciliation pass.
            "origin_kind": state.origin_kind,
            "origin_key": state.origin_key,
            "updated_at": state.updated_at,
        },
    }


def _resolve_item(request, media_type, source, media_id):
    """Return the addressed item, or an error response."""
    if not check_valid_type(media_type):
        return None, Response(
            {"detail": f"Invalid media type: {media_type}"},
            status=HTTP.BAD_REQUEST,
        )
    if not check_source_type(media_type, source):
        return None, Response(
            {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
            status=HTTP.BAD_REQUEST,
        )

    season_number = request.query_params.get("season_number")
    episode_number = request.query_params.get("episode_number")
    try:
        season_number = int(season_number) if season_number is not None else None
        episode_number = int(episode_number) if episode_number is not None else None
    except (TypeError, ValueError):
        return None, Response(
            {"detail": "season_number and episode_number must be integers."},
            status=HTTP.BAD_REQUEST,
        )

    queryset = resolve_item_queryset(
        media_id,
        source,
        media_type,
        season_number=season_number,
        episode_number=episode_number,
        library_media_type=request.query_params.get("library_media_type"),
    )

    # More than one candidate means the address was ambiguous. Picking one
    # would eventually write to the wrong library bucket.
    matches = list(queryset[:2])
    if not matches:
        return None, Response(
            {"detail": "No matching item."},
            status=HTTP.NOT_FOUND,
        )
    if len(matches) > 1:
        return None, Response(
            {"detail": "Ambiguous item; pass library_media_type."},
            status=HTTP.CONFLICT,
        )
    return matches[0], None


# /api/v1/media/[media_type]/[source]/[media_id]/watched-state/
class WatchedStateView(drf_views.APIView):
    """Read or set the canonical watched state for one item."""

    def get(self, request, media_type, source, media_id):
        """Return effective state and its provenance."""
        item, error = _resolve_item(request, media_type, source, media_id)
        if error is not None:
            return error

        state = effective_state(request.user, item)
        return Response(_serialize_state(state, item), status=HTTP.OK)

    def put(self, request, media_type, source, media_id):
        """Set watched state explicitly.

        This is a state assertion, not a play. It records no playback session
        and removes no history, which is what keeps "mark unwatched" distinct
        from "delete history".
        """
        item, error = _resolve_item(request, media_type, source, media_id)
        if error is not None:
            return error

        watched = request.data.get("watched")
        if not isinstance(watched, bool):
            return Response(
                {"detail": "`watched` must be a boolean."},
                status=HTTP.BAD_REQUEST,
            )

        expected_revision = request.headers.get("If-Match")
        if expected_revision is not None:
            try:
                expected_revision = int(expected_revision)
            except ValueError:
                return Response(
                    {"detail": "If-Match must be an integer revision."},
                    status=HTTP.BAD_REQUEST,
                )

        idempotency_key = request.headers.get("Idempotency-Key") or request.data.get(
            "client_event_id",
        )

        # Re-asserting "watched" keeps the time it was first marked, so a
        # repeated request is recognised as unchanged instead of recording a
        # new change whenever the clock has ticked into another second.
        current = effective_state(request.user, item)
        play_count = request.data.get("play_count")
        already_watched = bool(
            current
            and current.watched
            and (play_count is None or play_count == current.play_count),
        )
        try:
            result = record_state_change(
                request.user,
                item,
                watched=watched,
                play_count=play_count,
                watched_at=(
                    timezone.now() if watched and not already_watched else None
                ),
                origin_kind=WatchStateOrigin.LOCAL_API.value,
                origin_key="api",
                origin_event_id=idempotency_key,
                expected_revision=expected_revision,
            )
        except RevisionConflictError as error:
            return Response(
                {
                    "detail": str(error),
                    "revision": effective_state(request.user, item).revision,
                },
                status=HTTP.CONFLICT,
            )

        payload = _serialize_state(
            result.state or effective_state(request.user, item),
            item,
        )
        payload["replayed"] = result.replayed
        payload["unchanged"] = result.unchanged
        return Response(payload, status=HTTP.OK)


# /api/v1/sync/changes/
class WatchedStateChangeFeedView(drf_views.APIView):
    """Serve the ordered change feed for a synchronizing client."""

    def get(self, request):
        """Return changes after a cursor, in server order.

        The cursor is a server sequence, which is allocated at commit time, so
        paginating by it cannot skip a change that committed late.
        """
        raw_cursor = request.query_params.get("cursor", "0")
        try:
            cursor = int(raw_cursor)
        except ValueError:
            return Response(
                {"detail": "cursor must be an integer sequence."},
                status=HTTP.BAD_REQUEST,
            )

        limit, error = _integer_param(request, "limit", default=100, minimum=1)
        if error is not None:
            return error
        limit = min(limit, MAX_CHANGE_PAGE)

        binding, error = self._named_binding(request)
        if error is not None:
            return error
        pulls = binding is not None and binding.has_capability(CAPABILITY_WATCHED_PULL)
        if pulls:
            error = self._pull_problem(request.user, binding)
            if error is not None:
                return error

        oldest, newest = retained_change_range(request.user)
        # An unnamed pull keeps its old meaning: 0 is "from the start", exempt
        # from expiry. A pull client's 0 is a real position (an empty log at
        # snapshot time), so compaction past it is a gap like any other.
        if oldest is not None and (pulls or cursor > 0) and cursor < oldest - 1:
            # The client's position was compacted away. Serving the remaining
            # tail would look like a successful catch-up while silently
            # dropping everything between its cursor and what is left.
            return Response(
                {
                    "code": "cursor_expired",
                    "detail": (
                        "This cursor is older than the retained change log. "
                        "Take a fresh snapshot and resume from its sequence."
                    ),
                    "oldest_sequence": oldest,
                    "newest_sequence": newest,
                },
                status=HTTP.CONFLICT,
            )

        # Asking for changes after N is the client's proof it applied through N.
        # The server cannot know that any earlier, and advancing on delivery
        # would skip whatever a client fetched but died before applying.
        if binding is not None and cursor > 0:
            record_applied_position(binding, cursor)

        changes = changes_since(request.user, cursor, limit=limit)
        show_map = show_item_map([change.item for change in changes if change.item])
        results = [
            {
                "sequence": change.sequence,
                "revision": change.revision,
                "previous_revision": change.previous_revision,
                "kind": change.kind,
                "watched": change.watched,
                "play_count": change.play_count,
                "watched_at": change.watched_at,
                # Same value under the snapshot's name, so a client maps one
                # field name for both surfaces.
                "last_watched_at": change.watched_at,
                "media_id": change.item.media_id if change.item else None,
                "source": change.item.source if change.item else None,
                "media_type": change.item.media_type if change.item else None,
                **(item_reference(change.item, show_map) if change.item else {}),
                "origin_kind": change.origin_kind,
                "correlation_id": str(change.correlation_id),
            }
            for change in changes
        ]

        return Response(
            {
                "results": results,
                "next_cursor": results[-1]["sequence"] if results else cursor,
                "has_more": len(results) == limit,
                "oldest_sequence": oldest,
                "newest_sequence": newest,
            },
            status=HTTP.OK,
        )

    @staticmethod
    def _named_binding(request):
        """Return (binding, error) for the connection this pull speaks for.

        Identified by origin key so a client can hold several connections
        without them sharing a checkpoint. Unnamed pulls still work; they just
        record no position, and so never let the log compact past them. A name
        that matches nothing is refused rather than treated as unnamed: the
        client believes it has a connection, and silently serving it as if it
        had none hides that it must register again.
        """
        origin_key = request.query_params.get("connection")
        if not origin_key:
            return None, None
        binding = SyncBinding.objects.filter(
            user=request.user,
            origin_key=origin_key,
        ).first()
        if binding is None:
            return None, _inactive("missing")
        return binding, None

    @staticmethod
    def _pull_problem(user, binding):
        """Return the response refusing a pull client the feed, or None.

        A pull client may only resume from a position a snapshot pinned, taken
        after the projection was last repaired and while the log was being
        written. Anything else is a cursor that cannot be trusted.
        """
        problem = _pull_binding_problem(binding)
        if problem is not None:
            return _inactive(problem)
        if not watch_state_repair_complete(user):
            return _cursor_expired(
                "projection_incomplete",
                "Floppy is rebuilding this account's watched state. "
                "Take a fresh snapshot once it finishes.",
            )
        if _pinned_position(binding) is None:
            return _cursor_expired(
                "resnapshot_required",
                "No snapshot is pinned for this connection. Take a fresh "
                "snapshot and resume from its sequence.",
            )
        return None


# /api/v1/sync/watched-state/
class WatchedStateSnapshotView(drf_views.APIView):
    """Serve every watched movie and episode, compactly, for a first sync."""

    def get(self, request):
        """Return one page of watched states, ordered by item.

        Items are immutable keys, so paging by item id cannot skip a row that
        a concurrent change would have moved. The first page records the
        change-feed sequence and every later page repeats it: the client
        applies the feed from that sequence once the snapshot is complete, so
        a row changed mid-walk is at worst delivered twice, never lost.
        """
        origin_key = request.query_params.get("connection")
        if not origin_key:
            return Response(
                {
                    "code": "connection_required",
                    "detail": "Pass connection=<origin_key> of a registered client.",
                },
                status=HTTP.BAD_REQUEST,
            )
        binding = SyncBinding.objects.filter(
            user=request.user,
            origin_key=origin_key,
        ).first()
        problem = _pull_binding_problem(binding)
        if problem is not None:
            return _inactive(problem)
        # A snapshot read before the repair finishes would be short, and the
        # sequence it hands out would be trusted to be complete.
        if not watch_state_repair_complete(request.user):
            return _projection_incomplete_response()

        limit, error = _integer_param(
            request,
            "limit",
            default=DEFAULT_SNAPSHOT_PAGE,
            minimum=1,
        )
        if error is not None:
            return error
        limit = min(limit, MAX_SNAPSHOT_PAGE)

        cursor, error = _integer_param(request, "cursor", default=None, minimum=0)
        if error is not None:
            return error
        resume_cursor, error = _integer_param(
            request,
            "resume_cursor",
            default=None,
            minimum=0,
        )
        if error is not None:
            return error

        if cursor is None:
            cursor = 0
            # Read before any row, so everything the rows miss is after it.
            resume_cursor = (
                WatchStateSequence.objects.filter(user=request.user)
                .values_list("last_sequence", flat=True)
                .first()
                or 0
            )
            # Pin it before any row is read, so compaction cannot overtake the
            # snapshot while the client is still walking it.
            pin_snapshot_position(binding, resume_cursor)
        elif resume_cursor is None:
            return Response(
                {"detail": "resume_cursor is required with cursor."},
                status=HTTP.BAD_REQUEST,
            )
        else:
            # Later pages echo the first page's value. It is the position the
            # client will resume the feed from, so it must be one the server
            # pinned: a value above it would skip changes silently.
            pinned = _pinned_position(binding)
            if pinned is None:
                return _cursor_expired(
                    "resnapshot_required",
                    "This snapshot's pin was dropped. Start the snapshot again.",
                )
            if resume_cursor > pinned.last_sequence:
                return Response(
                    {
                        "code": "invalid_resume_cursor",
                        "detail": "resume_cursor was not issued for this snapshot.",
                    },
                    status=HTTP.BAD_REQUEST,
                )

        # One extra row says whether another page exists without a second query.
        states = list(
            WatchState.objects.filter(
                user=request.user,
                watched=True,
                item__media_type__in=SNAPSHOT_MEDIA_TYPES,
                item_id__gt=cursor,
            )
            .select_related("item")
            .order_by("item_id")[: limit + 1],
        )
        has_more = len(states) > limit
        states = states[:limit]

        show_map = show_item_map([state.item for state in states])
        results = []
        for state in states:
            item = state.item
            show = show_map.get((item.source, item.media_id))
            results.append(
                {
                    "media_id": item.media_id,
                    "source": item.source,
                    "media_type": item.media_type,
                    **item_reference(item, show_map),
                    "title": item.title,
                    "series_title": show.title
                    if show and item.media_type == MediaTypes.EPISODE.value
                    else None,
                    "play_count": state.play_count,
                    "last_watched_at": state.last_watched_at,
                    # Same value under the change feed's name.
                    "watched_at": state.last_watched_at,
                },
            )

        return Response(
            {
                "results": results,
                "next_cursor": states[-1].item_id if states else cursor,
                "has_more": has_more,
                "resume_cursor": resume_cursor,
            },
            status=HTTP.OK,
        )


# /api/v1/sync/connections/
class SyncConnectionsView(drf_views.APIView):
    """Report what each connection is actually allowed and able to do."""

    def post(self, request):
        """Register the calling Kodi client as a pull-only connection.

        Idempotent on the client's own instance key. The binding holds
        ``watched.pull`` and nothing else Floppy would act on: no delivery is
        ever queued for it, no reconcile pass selects it, and its only effect
        is to turn on the change log the client then pulls from.

        Registration never overrides the owner. A connection they switched off,
        sent back for reapproval or paused is reported with a 409 and left as
        it is; only a brand-new or still-pending connection is activated.
        """
        data = request.data
        if not isinstance(data, dict):
            return Response(
                {"detail": "Request body must be a JSON object."},
                status=HTTP.BAD_REQUEST,
            )
        instance_key = data.get("instance_key")
        if not isinstance(instance_key, str) or not instance_key.strip():
            return Response(
                {"detail": "`instance_key` must be a non-empty string."},
                status=HTTP.BAD_REQUEST,
            )
        instance_key = instance_key.strip()
        label = data.get("label", "")
        if not isinstance(label, str):
            return Response(
                {"detail": "`label` must be a string."},
                status=HTTP.BAD_REQUEST,
            )
        label = label.strip()
        for name, value in (("instance_key", instance_key), ("label", label)):
            if len(value) > MAX_CONNECTION_FIELD:
                return Response(
                    {
                        "detail": (
                            f"`{name}` must be at most "
                            f"{MAX_CONNECTION_FIELD} characters."
                        ),
                    },
                    status=HTTP.BAD_REQUEST,
                )

        with transaction.atomic():
            return self._register(request.user, instance_key, label)

    @staticmethod
    def _register(user, instance_key, label):
        """Create or look up the binding, and activate it only if it is new."""
        existing = SyncBinding.objects.filter(
            user=user,
            client_kind=SyncClientKind.KODI.value,
            instance_key=instance_key,
            profile_key="",
        ).first()
        if existing is None and (
            sum(
                binding.has_capability(CAPABILITY_WATCHED_PULL)
                for binding in SyncBinding.objects.filter(user=user)
            )
            >= MAX_PULL_CONNECTIONS
        ):
            return Response(
                {
                    "code": "connection_limit",
                    "detail": (
                        f"At most {MAX_PULL_CONNECTIONS} pull connections per "
                        "account. Remove one in Integrations first."
                    ),
                },
                status=HTTP.CONFLICT,
            )

        binding, created = get_or_create_binding(
            user,
            SyncClientKind.KODI.value,
            instance_key=instance_key,
            label=label,
        )
        if binding.kill_switch:
            return _inactive("kill_switch")
        if binding.status == SyncBindingStatus.DISABLED.value:
            return _inactive("disabled")
        if binding.status == SyncBindingStatus.NEEDS_REAPPROVAL.value:
            return _inactive("needs_reapproval")

        if binding.status == SyncBindingStatus.PENDING.value:
            # Whatever position it held belongs to an earlier life.
            reset_pull_positions(binding=binding)
        if not binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_WATCHED_PULL):
            # Merged, never replaced: approvals the owner gave stay.
            activate_binding(
                binding,
                capabilities=[*binding.approved_capabilities, CAPABILITY_WATCHED_PULL],
                directions=[
                    *binding.approved_directions,
                    SyncDirection.OUTBOUND.value,
                ],
            )
        if label and binding.label != label:
            binding.label = label
            binding.save(update_fields=["label", "updated_at"])

        return Response(
            {
                "id": binding.pk,
                "client_kind": binding.client_kind,
                "label": binding.label,
                "status": binding.status,
                "directions": binding.approved_directions,
                "capabilities": binding.approved_capabilities,
                "origin_key": binding.origin_key,
                # No pinned position means the client has nothing to resume
                # from: it has never taken a snapshot, or the last one was voided.
                "resnapshot_required": _pinned_position(binding) is None,
            },
            status=HTTP.CREATED if created else HTTP.OK,
        )

    def get(self, request):
        """Return connections, their directions, and unavailable capabilities."""
        from integrations.state.outbound import get_adapter

        _, newest_watched = retained_change_range(request.user)
        _, newest_progress = retained_progress_range(request.user)
        newest_by_resource = {
            WATCHED_STATE_RESOURCE: newest_watched,
            PROGRESS_RESOURCE: newest_progress,
        }

        results = []
        for binding in SyncBinding.objects.filter(user=request.user):
            adapter = get_adapter(binding)
            supported = set(adapter.CAPABILITIES) if adapter is not None else set()
            approved = set(binding.approved_capabilities or [])
            # Served by Floppy itself, so no provider adapter vouches for it.
            supported |= approved & {CAPABILITY_WATCHED_PULL}

            results.append(
                {
                    "id": binding.pk,
                    "client_kind": binding.client_kind,
                    "label": binding.label,
                    "status": binding.status,
                    "directions": binding.approved_directions or [],
                    "capabilities": sorted(approved & supported),
                    # Named explicitly rather than omitted: a direction the
                    # user asked for and cannot have is a capability
                    # limitation, and saying nothing reads as success.
                    "unavailable_capabilities": sorted(approved - supported),
                    # A client needs this to name itself when pulling a change
                    # feed; without it no checkpoint can ever be recorded, and
                    # the change log can never compact.
                    "origin_key": binding.origin_key,
                    "last_reconciled_at": binding.last_reconciled_at,
                    "last_error_message": binding.last_error_message,
                    "pending_deliveries": binding.deliveries.filter(
                        status=OutboundDeliveryStatus.PENDING.value,
                    ).count(),
                    # Counted separately and never folded into "pending": a
                    # failed write that reads as still-in-progress is the
                    # silent failure this whole surface exists to prevent.
                    "failed_deliveries": binding.deliveries.filter(
                        status=OutboundDeliveryStatus.FAILED.value,
                    ).count(),
                    "open_conflicts": binding.conflicts.filter(
                        status=StateConflictStatus.OPEN.value,
                    ).count(),
                    "unresolved_references": binding.unresolved_references.filter(
                        dismissed_at__isnull=True,
                    ).count(),
                    "checkpoints": self._checkpoints(binding, newest_by_resource),
                },
            )

        return Response({"results": results}, status=HTTP.OK)

    @staticmethod
    def _checkpoints(binding, newest_by_resource):
        """Report where this connection has got to, and how far behind it is.

        "Behind" is the number the user actually acts on: a connection that
        looks healthy but sits ten thousand changes back is not working, and
        neither a status field nor a last-seen timestamp shows that.
        """
        rows = []
        for checkpoint in SyncCheckpoint.objects.filter(binding=binding):
            newest = newest_by_resource.get(checkpoint.resource)
            rows.append(
                {
                    "resource": checkpoint.resource,
                    "direction": checkpoint.direction,
                    "last_sequence": checkpoint.last_sequence,
                    "behind_by": (
                        max(newest - checkpoint.last_sequence, 0)
                        if newest is not None
                        else None
                    ),
                    "updated_at": checkpoint.updated_at,
                },
            )
        return rows


# /api/v1/sync/conflicts/
class SyncConflictsView(drf_views.APIView):
    """List disagreements waiting for a person."""

    def get(self, request):
        """Return open conflicts."""
        conflicts = StateConflict.objects.filter(
            user=request.user,
            status=StateConflictStatus.OPEN.value,
        ).select_related("item", "binding")

        return Response(
            {
                "results": [
                    {
                        "id": conflict.pk,
                        "reason": conflict.reason,
                        "media_id": conflict.item.media_id,
                        "source": conflict.item.source,
                        "media_type": conflict.item.media_type,
                        "client_kind": conflict.binding.client_kind,
                        "local": conflict.local_snapshot,
                        "remote": conflict.remote_snapshot,
                        "base": conflict.base_snapshot,
                        "occurrence_count": conflict.occurrence_count,
                        "updated_at": conflict.updated_at,
                    }
                    for conflict in conflicts
                ],
            },
            status=HTTP.OK,
        )


# /api/v1/sync/conflicts/[conflict_id]/resolve/
class SyncConflictResolveView(drf_views.APIView):
    """Settle one disagreement with the state a person chose."""

    def post(self, request, conflict_id):
        """Resolve a conflict, creating a new revision."""
        from integrations.state.apply import resolve_conflict

        conflict = StateConflict.objects.filter(
            pk=conflict_id,
            user=request.user,
            status=StateConflictStatus.OPEN.value,
        ).first()
        if conflict is None:
            return Response(
                {"detail": "No open conflict with that id."},
                status=HTTP.NOT_FOUND,
            )

        watched = request.data.get("watched")
        if not isinstance(watched, bool):
            return Response(
                {"detail": "`watched` must be a boolean."},
                status=HTTP.BAD_REQUEST,
            )

        result = resolve_conflict(
            conflict,
            watched=watched,
            play_count=request.data.get("play_count"),
        )

        return Response(
            _serialize_state(result.state, conflict.item),
            status=HTTP.OK,
        )
