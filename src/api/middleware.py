import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.conf import settings
from django.db import IntegrityError
from django.http import JsonResponse
from django.template.response import ContentNotRenderedError, TemplateResponse

logger = logging.getLogger(__name__)

_TRACKED_MEDIA_CONSTRAINT_SUFFIX = "_unique_item_user"


def _is_sqlite_tracked_media_unique_error(exception):
    """Return whether SQLite reports the tracked-media user/item constraint."""
    message = str(exception).lower()
    marker = "unique constraint failed:"
    if marker not in message:
        return False

    raw_columns = message.split(marker, 1)[1].strip().split(",")
    if len(raw_columns) != 2:
        return False

    columns = []
    for raw_column in raw_columns:
        table, separator, column = raw_column.strip().rpartition(".")
        if not separator:
            return False
        columns.append((table, column))

    (first_table, first_column), (second_table, second_column) = columns
    return (
        first_table == second_table
        and first_table.startswith("app_")
        and {first_column, second_column} == {"user_id", "item_id"}
    )


def is_tracked_media_unique_error(exception):
    """Return whether an IntegrityError is the tracked-media duplicate constraint.

    PostgreSQL exposes the constraint name through the driver diagnostic. SQLite
    reports the constrained columns in the exception text. Keep both checks here
    so API behavior does not depend on the selected database backend.
    """
    if not isinstance(exception, IntegrityError):
        return False

    cause = exception.__cause__ or exception
    diagnostic = getattr(cause, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", "") or ""
    if constraint_name.endswith(_TRACKED_MEDIA_CONSTRAINT_SUFFIX):
        return True

    message = str(cause).lower()
    if "duplicate key" in message and _TRACKED_MEDIA_CONSTRAINT_SUFFIX in message:
        return True

    return _is_sqlite_tracked_media_unique_error(cause)


def _is_media_collection_post(request, path):
    """Return whether this is POST /api/v1/media/{media_type}."""
    if getattr(request, "method", "").upper() != "POST":
        return False
    parts = path.strip("/").split("/")
    return len(parts) == 4 and parts[:3] == ["api", "v1", "media"]


class ApiJsonErrorMiddleware:
    """Convert HTML error responses for API paths into JSON responses."""

    def __init__(self, get_response):  # noqa: D107
        self.get_response = get_response

    def __call__(self, request):  # noqa: D102
        response = self.get_response(request)
        path = self._get_request_path(request)

        if path.startswith("/api/") and response is not None:
            response = self._handle_template_response(response, path)
            status = getattr(response, "status_code", HTTP.OK)
            content_type = self._get_content_type(response)

            if self._should_convert_to_json(status, content_type):
                return self._build_json_error_response(response, status)

        return response

    def _get_request_path(self, request):
        """Safely extract the request path."""
        try:
            return request.path or ""
        except Exception:
            return ""

    def _handle_template_response(self, response, path):
        """Render TemplateResponse if needed."""
        if isinstance(response, TemplateResponse):
            try:
                response = response.render()
            except ContentNotRenderedError:
                logger.exception(
                    "TemplateResponse could not be rendered for %s",
                    path,
                )
            except Exception:
                logger.exception(
                    "Error while rendering TemplateResponse for %s",
                    path,
                )
        return response

    def _get_content_type(self, response):
        """Extract content type from response."""
        if hasattr(response, "headers"):
            return response.headers.get("Content-Type", "")

        if hasattr(response, "get"):
            try:
                return response.get("Content-Type", "")
            except Exception:
                return getattr(response, "content_type", "")

        return getattr(response, "content_type", "")

    def _should_convert_to_json(self, status, content_type):
        """Determine if response should be converted to JSON."""
        if content_type and "application/json" in content_type:
            return False
        return status >= HTTP.BAD_REQUEST and (
            not content_type or "html" in content_type.lower()
        )

    def _build_json_error_response(self, response, status):
        """Build JSON error response."""
        try:
            detail = HTTP(status).phrase
        except ValueError:
            detail = "Unknown status"

        payload = {"detail": detail}

        if settings.DEBUG and hasattr(response, "content"):
            detail = self._extract_debug_detail(response)
            if detail:
                payload["debug_html_snippet"] = detail[:2000]

        return JsonResponse(payload, status=status)

    def _extract_debug_detail(self, response):
        """Extract debug detail from response content."""
        try:
            return response.content.decode(errors="ignore")
        except Exception:
            return None

    def process_exception(self, request, exception):
        """Intercept unhandled exceptions for API paths and return JSON.

        This prevents Django from rendering the HTML technical 500 page
        (when DEBUG=True) for API calls.
        """
        path = self._get_request_path(request)

        if not path.startswith("/api/"):
            return None

        if _is_media_collection_post(request, path) and is_tracked_media_unique_error(
            exception,
        ):
            logger.info("Tracked media create conflict: %s", path)
            return JsonResponse(
                {"detail": "Conflict. Media is already tracked."},
                status=HTTP.CONFLICT,
            )

        logger.exception("Unhandled exception during API request: %s", path)

        detail = str(exception) if settings.DEBUG else "Internal server error."

        return JsonResponse({"detail": detail}, status=HTTP.INTERNAL_SERVER_ERROR)
