"""Authenticated API controls for durable metadata snapshots."""

import copy
from http import HTTPStatus as HTTP  # noqa: N814

from django.core.exceptions import ImproperlyConfigured
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import metadata_snapshots, network_policy
from app.models import MetadataSnapshot
from app.providers import services

from .fork_views_metadata import _owned_media_queryset
from .helpers import check_valid_type


class MetadataCacheRequestError(ValueError):
    """Report one invalid metadata cache request field."""


def _optional_integer(value, field_name):
    """Return one optional non-negative integer or raise a request error."""
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        msg = f"'{field_name}' must be a non-negative integer."
        raise MetadataCacheRequestError(msg) from error
    if parsed < 0:
        msg = f"'{field_name}' must be a non-negative integer."
        raise MetadataCacheRequestError(msg)
    return parsed


def _request_identity(request, media_type, source, media_id):
    """Build one metadata identity from route and query parameters."""
    season_numbers = request.query_params.getlist("season_number")
    return metadata_snapshots.build_metadata_identity(
        media_type,
        media_id,
        source,
        season_numbers or None,
        _optional_integer(
            request.query_params.get("episode_number"),
            "episode_number",
        ),
        request.query_params.get("language"),
        request.query_params.get("edition_id"),
    )


def _owned_items(user, identity):
    """Return matching Items that the authenticated user tracks."""
    return [
        item
        for item in metadata_snapshots.matching_items(identity)
        if _owned_media_queryset(user, item).exists()
    ]


def _ensure_local_snapshot(identity, items):
    """Return the snapshot, creating a local copy from an owned Item if needed."""
    snapshot = MetadataSnapshot.objects.filter(cache_key=identity.cache_key).first()
    if snapshot is None and items:
        snapshot = metadata_snapshots._persist_local_snapshot(
            identity,
            items[0],
            origin=MetadataSnapshot.Origin.API,
        )
    return snapshot


def _local_response_payload(identity, items, snapshot, policy):
    """Return separate metadata and cache objects without a provider call."""
    payload = metadata_snapshots._local_payload(snapshot, items)
    if payload is None:
        return None

    fresh = metadata_snapshots._snapshot_is_fresh(
        snapshot,
        policy=policy,
        identity=identity,
    )
    incomplete = metadata_snapshots._payload_needs_completion(payload, identity)
    state = snapshot.state if snapshot is not None else MetadataSnapshot.State.LOCAL
    annotated = metadata_snapshots._annotate_payload(
        payload,
        identity=identity,
        policy=policy,
        snapshot=snapshot,
        state=state,
        source="snapshot" if snapshot and snapshot.payload else "item",
        stale=not fresh or incomplete,
    )
    cache_state = annotated.pop("_floppy_cache")
    return {
        "metadata": annotated,
        "cache": cache_state,
    }


def _error_response(error):
    """Convert safe configuration and identity errors into a 400 response."""
    return Response({"detail": str(error)}, status=HTTP.BAD_REQUEST)


def _build_request_context(request, media_type, source, media_id):
    """Validate the route and return identity, ownership, policy, and snapshot."""
    if not check_valid_type(media_type):
        msg = "Unsupported media type."
        raise MetadataCacheRequestError(msg)
    identity = _request_identity(request, media_type, source, media_id)
    items = _owned_items(request.user, identity)
    if not items:
        return identity, [], None, None
    policy = metadata_snapshots.get_metadata_policy()
    snapshot = _ensure_local_snapshot(identity, items)
    return identity, items, policy, snapshot


class MetadataCachePolicyView(drf_views.APIView):
    """Return non-secret cache and network policy for API clients."""

    def get(self, request):
        """Return the effective instance policy and supported request controls."""
        del request
        try:
            policy = metadata_snapshots.get_metadata_policy()
            network_mode = network_policy.get_network_mode()
            allowlist = (
                sorted(network_policy.get_provider_allowlist())
                if network_mode == "restricted"
                else []
            )
        except ImproperlyConfigured as error:
            return _error_response(error)

        return Response(
            {
                "metadata": policy.public_dict(),
                "network": {
                    "mode": network_mode,
                    "allowed_providers": allowlist,
                },
                "request": {
                    "query_parameters": [
                        "season_number",
                        "episode_number",
                        "language",
                        "edition_id",
                    ],
                    "refresh_modes": ["queue", "wait"],
                },
            },
            status=HTTP.OK,
        )


class MetadataCacheView(drf_views.APIView):
    """Read a local copy or start an explicit metadata refresh."""

    def get(self, request, media_type, source, media_id):
        """Return local metadata without making an external request."""
        try:
            identity, items, policy, snapshot = _build_request_context(
                request,
                media_type,
                source,
                media_id,
            )
        except (
            ImproperlyConfigured,
            MetadataCacheRequestError,
            metadata_snapshots.MetadataSnapshotRejectedError,
        ) as error:
            return _error_response(error)

        if not items:
            return Response(
                {"detail": "Item not found in your library."},
                status=HTTP.NOT_FOUND,
            )
        response_payload = _local_response_payload(
            identity,
            items,
            snapshot,
            policy,
        )
        if response_payload is None:
            return Response(
                {"detail": "No local metadata is available."},
                status=HTTP.NOT_FOUND,
            )
        return Response(response_payload, status=HTTP.OK)

    def post(self, request, media_type, source, media_id):
        """Queue a refresh or wait for one while retaining the local copy."""
        try:
            identity, items, policy, snapshot = _build_request_context(
                request,
                media_type,
                source,
                media_id,
            )
        except (
            ImproperlyConfigured,
            MetadataCacheRequestError,
            metadata_snapshots.MetadataSnapshotRejectedError,
        ) as error:
            return _error_response(error)

        if not items:
            return Response(
                {"detail": "Item not found in your library."},
                status=HTTP.NOT_FOUND,
            )

        refresh_mode = str(request.data.get("mode", "queue") or "queue").casefold()
        if refresh_mode not in {"queue", "wait"}:
            return Response(
                {"detail": "'mode' must be 'queue' or 'wait'."},
                status=HTTP.BAD_REQUEST,
            )

        if refresh_mode == "wait":
            try:
                refreshed = services.get_media_metadata(
                    **identity.task_kwargs(),
                    _floppy_refresh=True,
                    _floppy_origin=MetadataSnapshot.Origin.API,
                )
            except services.ProviderAPIError:
                local_payload = _local_response_payload(
                    identity,
                    items,
                    MetadataSnapshot.objects.filter(
                        cache_key=identity.cache_key,
                    ).first(),
                    policy,
                )
                if local_payload is not None:
                    return Response(local_payload, status=HTTP.OK)
                return Response(
                    {"detail": "Metadata refresh failed and no local copy exists."},
                    status=HTTP.SERVICE_UNAVAILABLE,
                )

            refreshed = copy.deepcopy(refreshed)
            cache_state = refreshed.pop("_floppy_cache", None)
            return Response(
                {"metadata": refreshed, "cache": cache_state},
                status=HTTP.OK,
            )

        queued, snapshot = metadata_snapshots._queue_refresh(
            identity,
            snapshot,
            policy=policy,
        )
        response_payload = _local_response_payload(
            identity,
            items,
            snapshot,
            policy,
        ) or {"metadata": None, "cache": None}
        response_payload["queued"] = queued
        return Response(
            response_payload,
            status=HTTP.ACCEPTED if queued else HTTP.OK,
        )
