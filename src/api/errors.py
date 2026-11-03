"""Machine-readable API errors for technical database failures (#1609)."""

from __future__ import annotations

from http import HTTPStatus

from django.http import JsonResponse

from app import db_diagnostics

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
