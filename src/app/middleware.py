import json
import logging
import threading
import time
from http import HTTPStatus
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.sessions.exceptions import SessionInterrupted
from django.db import DatabaseError, connection
from django.db.utils import OperationalError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, resolve_url
from django.urls import reverse
from django.utils import translation

from app import db_diagnostics, request_timing, stall_watchdog
from app.db_retry import is_contention_error, is_lock_error, is_retryable_error
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


class UserLanguageMiddleware:
    """Activate the authenticated user's preferred UI language, if set."""

    def __init__(self, get_response):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request):
        """Activate translation for the request's language."""
        user_language = getattr(request.user, "ui_language", "auto")
        if request.user.is_authenticated and user_language != "auto":
            language = user_language
        else:
            language = translation.get_language_from_request(request)

        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()
        try:
            response = self.get_response(request)
        finally:
            translation.deactivate()
        return response


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
    Beyond wall time it records where the time went, so a slow request can be
    told apart as computing (cpu_ms close to duration_ms), waiting on the
    database (db_ms) or waiting on a provider (provider_ms). inflight is how
    many requests this process was serving when the request finished, which
    shows a worker running out of threads. The same figures go to signed-in
    users in a Server-Timing header, readable in the browser as
    performance.getEntriesByType("navigation")[0].serverTiming.
    """

    _inflight = 0
    _inflight_lock = threading.Lock()

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response
        if settings.PERF_LOG_ENABLED:
            request_timing.install_boundaries()

    def __call__(self, request):
        """Time the request and count its queries, logging when over thresholds."""
        if not settings.PERF_LOG_ENABLED:
            return self.get_response(request)

        query_count = {"total": 0, "seconds": 0.0}

        def count_query(execute, sql, params, many, context):
            query_count["total"] += 1
            query_started = time.perf_counter()
            try:
                with request_timing.boundary("db"):
                    return db_diagnostics.track_query(
                        execute, sql, params, many, context
                    )
            finally:
                elapsed = time.perf_counter() - query_started
                query_count["seconds"] += elapsed
                request_timing.record_sql(sql, elapsed)

        provider_tally, tally_token = request_timing.begin()
        with self._inflight_lock:
            type(self)._inflight += 1
        start = time.perf_counter()
        cpu_start = time.thread_time()
        stall_token = (
            stall_watchdog.enter(request.method, request.path)
            if settings.PERF_STALL_WARN_MS > 0
            else None
        )
        stalled = False
        try:
            with connection.execute_wrapper(count_query):
                response = self.get_response(request)
        finally:
            if stall_token is not None:
                stalled = stall_watchdog.leave(stall_token)
            request_timing.end(tally_token)
            with self._inflight_lock:
                inflight = type(self)._inflight
                type(self)._inflight -= 1
        duration_ms = (time.perf_counter() - start) * 1000
        cpu_ms = (time.thread_time() - cpu_start) * 1000
        db_ms = query_count["seconds"] * 1000
        provider_ms = provider_tally["seconds"] * 1000
        boundaries = provider_tally["boundaries"]
        breakdown = {
            f"{name}_ms": boundaries.get(name, 0.0) * 1000
            for name in ("cache", "broker", "db_connect", "render", *sorted(
                set(boundaries) - {"cache", "broker", "db_connect", "render", "db", "provider"},
            ))
        }
        # Exclusive wall spans partition elapsed time. CPU is an overlapping
        # diagnostic, not another duration to subtract from this remainder.
        breakdown["unclassified_ms"] = max(
            0.0, duration_ms - sum(boundaries.values()) * 1000
        )
        boundary_fields = " ".join(
            f"{name}={value:.1f}" for name, value in breakdown.items()
        )

        if getattr(getattr(request, "user", None), "is_authenticated", False):
            response["Server-Timing"] = (
                f"total;dur={duration_ms:.0f}, cpu;dur={cpu_ms:.1f}, "
                f"db;dur={db_ms:.1f}, provider;dur={provider_ms:.1f}"
                + "".join(
                    f", {name.removesuffix('_ms')};dur={value:.1f}"
                    for name, value in breakdown.items()
                )
                + f', queries;desc="{query_count["total"]}"'
            )

        if (
            stalled
            or duration_ms >= settings.PERF_LOG_SLOW_REQUEST_MS
            or query_count["total"] >= settings.PERF_LOG_QUERY_COUNT_THRESHOLD
        ):
            logger.info(
                "slow_request method=%s path=%s status=%s duration_ms=%.0f queries=%s "
                "cpu_ms=%.1f db_ms=%.1f provider_ms=%.1f provider_calls=%s inflight=%s %s",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                query_count["total"],
                cpu_ms,
                db_ms,
                provider_ms,
                provider_tally["calls"],
                inflight,
                boundary_fields,
            )
        return response


class DatabaseRetryMiddleware:
    """Retry requests when database operations fail with retryable errors."""

    def __init__(self, get_response):
        """Initialize the middleware with the get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request with retry logic for database errors."""
        with db_diagnostics.bind_request(request):
            return self._run(request)

    def _run(self, request):
        max_retries = 5
        # A lock error arrives only after SQLite's busy_timeout (30 s by
        # default) ran out, so each retry of the whole view can wait that
        # long again; five of them outlasted the gunicorn timeout. One retry
        # still covers a writer that just finished.
        max_lock_retries = 1
        base_delay = 0.1
        backoff = 2.0
        attempt = 0

        while True:
            try:
                return self.get_response(request)
            except DatabaseError as error:
                # Only retry retryable errors while under the retry cap.
                if not (is_contention_error(error) or is_retryable_error(error)):
                    raise

                db_diagnostics.report_database_error(error, operation="request")

                if request.method != "GET":
                    logger.exception(
                        "Database error on %s request, not retrying",
                        request.method,
                    )
                    raise

                retry_cap = max_lock_retries if is_lock_error(error) else max_retries
                if attempt >= retry_cap:
                    response = self._contention_response(request, error)
                    if response is not None:
                        return response
                    raise

                error_type = "disk I/O" if "i/o" in str(error).lower() else "lock"
                sleep_for = base_delay * (backoff**attempt)
                logger.warning(
                    "Retrying %s after %s error (attempt %s/%s, sleeping %.2fs)",
                    request.path,
                    error_type,
                    attempt + 1,
                    retry_cap,
                    sleep_for,
                )
                time.sleep(sleep_for)
                attempt += 1

    def _contention_response(self, request, exception):
        if (
            request.method == "GET"
            and isinstance(exception, DatabaseError)
            and is_contention_error(exception)
            and should_mark_interactive_request(request)
        ):
            logger.warning(
                "Database contention on GET %s: %s",
                request.path,
                exception,
            )
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse(status=503)
            else:
                response = HttpResponse(
                    """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="6"><title>Loading</title></head>
<body style="font-family:system-ui;margin:3rem auto;max-width:36rem">
<p role="status">Waiting for the database. This page will load automatically.</p>
<script>
const key = "floppy-db-retry:" + location.href;
let attempt = 5;
try {
  attempt = Number(sessionStorage.getItem(key) || 0);
  sessionStorage.setItem(key, String(attempt + 1));
} catch (error) { /* storage disabled */ }
setTimeout(() => location.replace(location.href), Math.min(5000, 250 * 2 ** Math.min(attempt, 5)));
</script></body></html>""",
                    status=503,
                )
            response["X-Floppy-Transient-DB"] = "contention"
            response["Retry-After"] = "1"
            response["Cache-Control"] = "no-store"
            return response
        return None

    def process_exception(self, request, exception):
        """Handle exceptions that weren't caught in __call__."""
        from integrations.import_scope import ImportOverwriteConflictError

        if isinstance(exception, ImportOverwriteConflictError):
            response = JsonResponse({"detail": str(exception)}, status=409)
            response["Retry-After"] = "1"
            return response
        response = self._contention_response(request, exception)
        if response is not None:
            return response
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
        if isinstance(exception, services.ProviderNotConfiguredError):
            return render_error_page(
                request,
                "500.html",
                status_code=503,
                page_title="Provider Not Configured",
                heading="Provider Not Configured",
                error_message=str(exception),
                exception=exception,
                extra_lines=[f"Provider: {exception.provider_label}"],
                extra_context={},
            )
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


class ProviderCredentialUserMiddleware:
    """Publish the request's user so their personal provider keys apply.

    Provider modules read credentials deep inside call chains that have no user
    argument. Rather than thread one through ~150 signatures, the user is
    published for the life of the request; Celery runs no middleware, so
    background jobs keep resolving the instance key.
    """

    def __init__(self, get_response):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request):
        """Scope the request's user to provider credential lookups."""
        from app.providers import credentials

        with credentials.current_user_scope(getattr(request, "user", None)):
            return self.get_response(request)


class DemoAccountGuardMiddleware:
    """Refuse account, credential and library-wide changes from the demo user.

    The demo login is public, so whatever it can change every visitor can. The
    preference pages and the account page guard themselves; this list covers
    the routes where one visitor could lock the rest out (tokens),
    attach credentials or external logins, or wipe the shared library. Reads
    are untouched.
    """

    MESSAGE = "This section is view-only for demo accounts."
    BLOCKED_ROUTES = frozenset(
        {
            "regenerate_token",
            "create_integration_token",
            "revoke_integration_token",
            "create_catalog_grant",
            "revoke_catalog_grant",
            "save_provider_credential",
            "save_personal_credential",
            "clear_provider_credential",
            "socialaccount_connections",
            "notifications",
            "update_tmdb_proxy",
            "plex_connect",
            "jellyfin_connect",
            "jellyfin_settings",
            "update_jellyseerr_settings",
            "update_plex_usernames",
            "bulk_delete_by_import_source",
            "bulk_delete_by_media_type",
            "rollback_import_run",
            "convert_anime_library",
            "convert_tv_library",
            "repair_duplicate_anime_libraries",
        },
    )

    def __init__(self, get_response):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request):
        """Pass the request through; refusals happen in process_view."""
        return self.get_response(request)

    def process_view(self, request, _view_func, _view_args, _view_kwargs):
        """Refuse a blocked route's writes for the demo user."""
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        if not getattr(getattr(request, "user", None), "is_demo", False):
            return None
        match = request.resolver_match
        if match is None or match.url_name not in self.BLOCKED_ROUTES:
            return None
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=HTTPStatus.FORBIDDEN)
            response["HX-Trigger"] = json.dumps(
                {"showToast": {"message": self.MESSAGE, "type": "error"}},
            )
            return response
        messages.error(request, self.MESSAGE)
        return redirect(request.path)
