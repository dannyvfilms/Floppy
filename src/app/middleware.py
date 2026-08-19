import logging
import time
from http import HTTPStatus
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.sessions.exceptions import SessionInterrupted
from django.db import connection
from django.db.utils import OperationalError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, resolve_url
from django.urls import reverse

from app.db_retry import is_retryable_error
from app.discover import tab_cache as discover_tab_cache
from app.error_views import format_exception_traceback, render_error_page
from app.interactive_requests import (
    mark_interactive_request,
    should_mark_interactive_request,
)
from app.models import Sources
from app.providers import services

logger = logging.getLogger(__name__)


class AutoLoginMiddleware:
    """Middleware to auto-login with a specific user."""

    def __init__(self, get_response):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request):
        """Handle authorization request."""
        auto_login_username = settings.FLOPPY_AUTO_LOGIN_USERNAME
        if auto_login_username and not request.user.is_authenticated:
            user_model = get_user_model()
            try:
                user = user_model.objects.get(username=auto_login_username)
                if user.is_active:
                    login(
                        request,
                        user,
                        backend="django.contrib.auth.backends.ModelBackend",
                    )
            except user_model.DoesNotExist:
                pass

        return self.get_response(request)


class NoStoreHtmlMiddleware:
    """Stop browsers heuristically caching rendered HTML.

    Django sends no Cache-Control on ordinary HTML responses, which leaves the
    document heuristically cacheable. iOS Safari (and the installed PWA, which
    shares Safari's HTTP cache) takes that as licence to keep serving markup it
    fetched days ago, so template fixes never reach the device until the user
    deletes and re-adds the PWA. That is what made #442 look unfixable.

    Static assets are excluded: they are cache-busted by mtime and are the one
    thing that *should* stay in the cache.
    """

    def __init__(self, get_response):
        """Store the next middleware in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Mark HTML responses as uncacheable."""
        response = self.get_response(request)

        if request.path_info.startswith(("/static/", "/media/")):
            return response

        if response.has_header("Cache-Control"):
            return response

        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"

        return response


class HtmxAuthRedirectMiddleware:
    """Turn login redirects into HX-Redirect for htmx requests.

    ``LoginRequiredMiddleware`` answers a lost session with a plain 302 to the
    login page. htmx follows that redirect transparently, gets a 200 carrying
    the whole login document, and swaps it into whatever fragment slot made the
    request - so a poller paints a login form partway down the page (#386).
    Answering with 204 + HX-Redirect makes htmx navigate instead.
    """

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Rewrite login redirects on htmx requests into HX-Redirect."""
        response = self.get_response(request)

        if not request.headers.get("HX-Request"):
            return response
        if response.status_code not in {301, 302}:
            return response

        location = response.headers.get("Location", "")
        if urlparse(location).path != urlparse(resolve_url(settings.LOGIN_URL)).path:
            return response

        redirect_response = HttpResponse(status=204)
        redirect_response.headers["HX-Redirect"] = location
        return redirect_response


class RequestPerformanceLoggingMiddleware:
    """Log slow or query-heavy requests so regressions are visible in production.

    Query counting uses connection.execute_wrapper so it works without DEBUG.
    """

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Time the request and count its queries, logging when over thresholds."""
        if not settings.PERF_LOG_ENABLED:
            return self.get_response(request)

        query_count = {"total": 0}

        def count_query(execute, sql, params, many, context):
            query_count["total"] += 1
            return execute(sql, params, many, context)

        start = time.perf_counter()
        with connection.execute_wrapper(count_query):
            response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000

        if (
            duration_ms >= settings.PERF_LOG_SLOW_REQUEST_MS
            or query_count["total"] >= settings.PERF_LOG_QUERY_COUNT_THRESHOLD
        ):
            logger.info(
                "slow_request method=%s path=%s status=%s duration_ms=%.0f queries=%s",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                query_count["total"],
            )
        return response


class DatabaseRetryMiddleware:
    """Retry requests when database operations fail with retryable errors."""

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request with retry logic for database errors."""
        max_retries = 5
        base_delay = 0.1
        backoff = 2.0
        attempt = 0

        while True:
            try:
                return self.get_response(request)
            except OperationalError as error:
                # Only retry retryable errors while under the retry cap.
                if not is_retryable_error(error) or attempt >= max_retries:
                    raise

                if request.method != "GET":
                    logger.exception(
                        "Database error on %s request, not retrying",
                        request.method,
                    )
                    raise

                error_type = "disk I/O" if "i/o" in str(error).lower() else "lock"
                sleep_for = base_delay * (backoff**attempt)
                logger.warning(
                    "Retrying %s after %s error (attempt %s/%s, sleeping %.2fs)",
                    request.path,
                    error_type,
                    attempt + 1,
                    max_retries,
                    sleep_for,
                )
                time.sleep(sleep_for)
                attempt += 1

    def process_exception(self, request, exception):
        """Handle exceptions that weren't caught in __call__."""
        if isinstance(exception, OperationalError) and is_retryable_error(exception):
            error_type = "disk I/O" if "i/o" in str(exception).lower() else "lock"
            logger.error(
                "Database %s error on %s %s: %s",
                error_type,
                request.method,
                request.path,
                exception,
            )
            return render_error_page(
                request,
                "500.html",
                status_code=503,
                page_title="Service Unavailable",
                heading="Service Unavailable",
                error_message=(
                    f"Database {error_type} error. Please try again in a moment."
                ),
                exception=exception,
            )
        return None


class SessionInterruptedMiddleware:
    """Recover from a session row deleted mid-request.

    A stale tab's OAuth callback can race session cycling from another login
    tab; recover instead of surfacing Django's default 400 page (#622).
    """

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request, catching a mid-flight session interruption."""
        try:
            return self.get_response(request)
        except SessionInterrupted:
            logger.warning(
                "Session interrupted for %s %s (likely a stale tab racing "
                "a session cycle elsewhere)",
                request.method,
                request.path,
            )
            return redirect(settings.LOGIN_REDIRECT_URL)


class ProviderAPIErrorMiddleware:
    """Middleware to handle ProviderAPIError exceptions."""

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request and handle exceptions."""
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Handle exceptions raised during request processing."""
        if isinstance(exception, services.ProviderAPIError):
            is_provider_unreachable = exception.status_code is None
            extra_context = {}
            extra_lines = [
                f"Provider: {exception.provider_label}",
                (
                    f"Provider status: {exception.status_code}"
                    if exception.status_code is not None
                    else "Provider status: unavailable"
                ),
            ]

            if (
                exception.provider == Sources.HARDCOVER.value
                and exception.status_code == HTTPStatus.UNAUTHORIZED
            ):
                extra_context = {
                    "error_support_title": "Hardcover token expired",
                    "error_support_text": (
                        "Hardcover API keys expire after one year. The bundled "
                        "key in src/config/settings.py needs to be refreshed by a "
                        "maintainer."
                    ),
                    "error_support_url": (
                        "https://docs.hardcover.app/api/getting-started/"
                    ),
                    "error_support_link_label": "Open Hardcover API docs",
                }
                extra_lines.append(
                    "Hardcover API keys expire after one year; the bundled key "
                    "in src/config/settings.py needs to be refreshed by a "
                    "maintainer."
                )
            return render_error_page(
                request,
                "500.html",
                status_code=503 if is_provider_unreachable else 500,
                page_title="Service Unavailable"
                if is_provider_unreachable
                else "Server Error",
                heading="Service Unavailable"
                if is_provider_unreachable
                else "Something Went Wrong",
                error_message=str(exception),
                exception=exception,
                extra_lines=extra_lines,
                extra_context=extra_context,
            )
        return None


class ErrorCaptureMiddleware:
    """Capture exception details so the 500 handler can render tracebacks."""

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Pass the request through the middleware chain."""
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Persist traceback details for the custom error handler."""
        request._floppy_captured_exception = exception
        request._floppy_captured_traceback = format_exception_traceback(exception)


class DiscoverWarmupMiddleware:
    """Schedule Discover warmup in the background for active users."""

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Mark active browsing and queue Discover warmup when eligible."""
        if should_mark_interactive_request(request):
            try:
                mark_interactive_request()
            except Exception as error:
                logger.debug(
                    "Skipping interactive-request marker for %s due to error: %s",
                    request.path,
                    error,
                )
        if self._should_warm_discover(request):
            try:
                discover_tab_cache.maybe_schedule_user_warmup(request.user)
            except Exception as error:
                logger.debug(
                    "Skipping Discover warmup for %s due to error: %s",
                    request.path,
                    error,
                )
        return self.get_response(request)

    def _should_warm_discover(self, request: HttpRequest) -> bool:
        if (
            request.method not in {"GET", "HEAD"}
            or request.headers.get("HX-Request") == "true"
        ):
            return False

        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False) or not getattr(
            user,
            "id",
            None,
        ):
            return False

        path = request.path_info or ""
        if path == "/serviceworker.js" or path.startswith(
            ("/api/", "/admin/", "/static/", "/media/", "/_debug/"),
        ):
            return False
        normalized_path = path.rstrip("/") or "/"
        discover_path = reverse("discover").rstrip("/") or "/"
        if normalized_path != discover_path:
            return False
        if request.GET.get("discover_debug") in {"1", "true", "True"}:
            return False

        accept = request.headers.get("Accept", "")
        return not accept or "text/html" in accept or "*/*" in accept
