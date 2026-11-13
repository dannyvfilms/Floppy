"""Optional ``Idempotency-Key`` support for appending writes (#1613).

A client that times out after sending ``POST /media/{type}/`` cannot tell
whether the play was committed. Resending with the same key replays the first
success instead of appending a second play. The record lives in the default
cache, so it survives a retry but not a cache flush; a flushed or expired key
behaves like a first request.
"""

from __future__ import annotations

import functools
import hashlib
import json
from http import HTTPStatus

from django.core.cache import cache
from rest_framework.response import Response

HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replayed"
MAX_KEY_LENGTH = 200
DONE_TTL = 24 * 60 * 60
PENDING_TTL = 5 * 60


def _fingerprint(request, media_type):
    body = request.data
    if hasattr(body, "dict"):
        body = body.dict()
    payload = json.dumps([media_type, body], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _error(detail, code, status):
    return Response({"detail": detail, "code": code}, status=status)


def idempotent_create(view):
    """Replay the first successful response for a repeated Idempotency-Key."""

    @functools.wraps(view)
    def wrapper(self, request, media_type, *args, **kwargs):
        key = request.headers.get(HEADER)
        if not key:
            return view(self, request, media_type, *args, **kwargs)
        if len(key) > MAX_KEY_LENGTH:
            return _error(
                f"{HEADER} must be at most {MAX_KEY_LENGTH} characters.",
                "IDEMPOTENCY_KEY_INVALID",
                HTTPStatus.BAD_REQUEST,
            )

        digest = hashlib.sha256(key.encode()).hexdigest()
        cache_key = f"api-idempotency:{request.user.id}:{digest}"
        fingerprint = _fingerprint(request, media_type)

        # ``add`` is atomic, so two concurrent sends cannot both pass.
        if not cache.add(
            cache_key,
            {"state": "pending", "fingerprint": fingerprint},
            PENDING_TTL,
        ):
            record = cache.get(cache_key) or {}
            if record.get("fingerprint") != fingerprint:
                return _error(
                    f"{HEADER} was already used with a different request.",
                    "IDEMPOTENCY_KEY_REUSED",
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            if record.get("state") == "done":
                response = Response(
                    {**record["data"], "idempotent_replayed": True},
                    status=record["status"],
                )
                response[REPLAY_HEADER] = "true"
                return response
            return _error(
                "The first request with this key is still running; "
                "check the item's history before retrying.",
                "IDEMPOTENCY_IN_PROGRESS",
                HTTPStatus.CONFLICT,
            )

        try:
            response = view(self, request, media_type, *args, **kwargs)
        except BaseException:
            cache.delete(cache_key)
            raise
        if response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            cache.set(
                cache_key,
                {
                    "state": "done",
                    "fingerprint": fingerprint,
                    "status": response.status_code,
                    "data": response.data,
                },
                DONE_TTL,
            )
        else:
            # A refused write committed nothing, so the key stays reusable.
            cache.delete(cache_key)
        return response

    return wrapper
