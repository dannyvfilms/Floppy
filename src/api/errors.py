"""Machine-readable API errors for technical database failures (#1609)."""

from __future__ import annotations

import logging
from http import HTTPStatus

from django.http import JsonResponse
from rest_framework.response import Response

from app import db_diagnostics
from app.log_safety import exception_summary

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# ``validate_body`` returns prose; map the one refusal an agent must tell apart.
_INVALID_STATUS_DETAIL = "Invalid status value."


def validation_error_code(error):
    """Return ``{"code": ...}`` for a ``validate_body`` refusal that has one."""
    return {"code": "INVALID_STATUS"} if error == _INVALID_STATUS_DETAIL else {}


def database_busy_response(error, *, request=None, report=True):
    """Return a 503 JSON response for database contention, or ``None``.

    The original refusal (a generic 500) hid a retryable condition. The body
    keeps ``detail`` for existing clients and adds stable ``code`` and
    ``retryable`` fields for agents. A lock error already waited out SQLite's
    busy timeout, so the response is never retried server-side for POST.
    """
    if report:
        info = db_diagnostics.report_database_error(
            error,
            request=request,
            operation="api",
        )
    else:
        info = db_diagnostics.describe_database_error(error)
    if info is None:
        return None

    method = str(getattr(request, "method", "") or "").upper()
    retryable = info.retryable and method in _SAFE_METHODS
    payload = {
        "detail": info.detail,
        "code": info.code,
        "retryable": retryable,
    }
    if retryable and info.retry_after is not None:
        payload["retry_after"] = info.retry_after

    response = JsonResponse(payload, status=HTTPStatus.SERVICE_UNAVAILABLE)
    if retryable and info.retry_after is not None:
        response["Retry-After"] = str(info.retry_after)
    return response


def failure_response(detail, error, *, status, traceback=True):
    """Return ``{"detail": detail}`` and log the failure instead of returning it.

    For a caught exception whose text Floppy did not write: a provider, a
    library, the database. The log gets the exception class and, unless
    ``traceback`` is off, the traceback behind the redacting record factory.
    Turn it off where the text is known to carry a credential.
    """
    logger.warning(
        "%s error=%s",
        detail,
        exception_summary(error),
        exc_info=error if traceback else None,
    )
    return Response({"detail": detail}, status=status)
