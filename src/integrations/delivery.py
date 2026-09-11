"""Deduplication and delivery receipt gateway for integration events."""

import hashlib
import json
import logging
from collections.abc import Callable
from http import HTTPStatus as HTTP  # noqa: N814
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from rest_framework.response import Response

from .models import IntegrationEventReceipt, IntegrationToken

logger = logging.getLogger(__name__)



def calculate_payload_digest(payload: Any) -> str:
    """Calculate deterministic SHA-256 hex digest of sorted canonical JSON."""
    if isinstance(payload, (dict, list)):
        json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    elif isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, (dict, list)):
                json_str = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
            else:
                json_str = payload
        except (ValueError, TypeError):
            json_str = payload
    elif isinstance(payload, bytes):
        try:
            parsed = json.loads(payload.decode("utf-8"))
            if isinstance(parsed, (dict, list)):
                json_str = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
            else:
                json_str = payload.decode("utf-8", errors="replace")
        except Exception:
            json_str = payload.decode("utf-8", errors="replace")
    else:
        try:
            json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            json_str = str(payload)

    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def _replay_response(receipt) -> Response:
    """Return the stored response for a receipt being replayed."""
    body = None if receipt.response_status_code == HTTP.NO_CONTENT else receipt.response_body
    return Response(body, status=receipt.response_status_code)


def _conflict_response(client_event_id: str) -> Response:
    """Return the conflict for an event id reused with a different payload."""
    return Response(
        {
            "error": {
                "type": "conflict_error",
                "code": "idempotency_conflict",
                "message": (
                    "The provided Idempotency-Key has already been used "
                    "with a different request payload."
                ),
                "param": "Idempotency-Key",
                "correlation_id": f"rec_{client_event_id}",
            },
        },
        status=HTTP.CONFLICT,
    )


def _settle(receipt, digest: str, client_event_id: str) -> tuple[Response, bool]:
    """Resolve an existing receipt into a replay or a conflict."""
    if receipt.payload_digest == digest:
        return (_replay_response(receipt), True)
    return (_conflict_response(client_event_id), False)


def get_or_record_receipt(
    user: Any,
    client_event_id: str,
    payload: Any,
    execute_fn: Callable[[], Response],
    token: IntegrationToken | None = None,
    binding: Any = None,
) -> tuple[Response, bool]:
    """Retrieve existing cached response or execute operation and persist receipt.

    Scoped to ``binding`` when the request has one, and to the user otherwise.
    Two devices on one account commonly mint the same client event id, so a
    user-wide scope would report the second device's first event as a conflict.

    Returns a tuple of (Response, is_replay).
    """
    digest = calculate_payload_digest(payload)
    scope = (
        {"binding": binding}
        if binding is not None
        else {"user": user, "binding__isnull": True}
    )

    receipt = IntegrationEventReceipt.objects.filter(
        client_event_id=client_event_id,
        **scope,
    ).first()
    if receipt is not None:
        return _settle(receipt, digest, client_event_id)

    response = execute_fn()

    if response.status_code < HTTP.INTERNAL_SERVER_ERROR:
        if response.data is not None:
            try:
                response_data = json.loads(json.dumps(response.data, cls=DjangoJSONEncoder))
            except Exception:
                response_data = response.data
        else:
            response_data = {}

        try:
            with transaction.atomic():
                IntegrationEventReceipt.objects.create(
                    user=user,
                    token=token,
                    binding=binding,
                    client_event_id=client_event_id,
                    payload_digest=digest,
                    response_status_code=response.status_code,
                    response_body=response_data,
                )
        except IntegrityError:
            # Another request with the same identity committed first. Its
            # receipt is the authority; this one settles against it.
            receipt = IntegrationEventReceipt.objects.filter(
                client_event_id=client_event_id,
                **scope,
            ).first()
            if receipt is not None:
                return _settle(receipt, digest, client_event_id)

    return (response, False)
