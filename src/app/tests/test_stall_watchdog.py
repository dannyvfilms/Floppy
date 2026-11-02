"""Tests for the in-flight stalled request watchdog."""

import threading
import time
from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.test.utils import override_settings

from app import stall_watchdog
from app.middleware import RequestPerformanceLoggingMiddleware


@override_settings(
    PERF_LOG_ENABLED=True,
    PERF_LOG_SLOW_REQUEST_MS=10_000,
    PERF_STALL_WARN_MS=50,
    PERF_STALL_MAX_REPORTS_PER_MINUTE=10,
)
class StallWatchdogTests(SimpleTestCase):
    """The watchdog reports a request while it is still running, once."""

    def setUp(self):
        """Reset the report window."""
        stall_watchdog._state["window_count"] = 0
        stall_watchdog._state["window_start"] = 0.0

    # A scanner thread started by an earlier test in this process is still
    # running and would report the request before the explicit scan below.
    # A threshold it can never reach, with the explicit scan given a later
    # clock, makes the count deterministic.
    @override_settings(PERF_STALL_WARN_MS=60_000)
    def test_reports_blocked_request_once_before_it_finishes(self):
        """A request held past the threshold logs route, age and stack once."""
        release = threading.Event()
        inside = threading.Event()

        def view(request):
            inside.set()
            release.wait(5)
            return HttpResponse("ok")

        middleware = RequestPerformanceLoggingMiddleware(view)
        request = RequestFactory().get("/medialist/music?token=SECRET")
        thread = threading.Thread(target=middleware, args=(request,))
        # The background scanner would report the request between the
        # threshold and this test's own scan, leaving the test with nothing
        # to count. Only the explicit scans below may run.
        with (
            mock.patch.object(stall_watchdog, "_ensure_thread"),
            self.assertLogs("app.stall_watchdog", level="WARNING") as logs,
        ):
            thread.start()
            inside.wait(2)
            later = time.monotonic() + 120
            self.assertEqual(stall_watchdog.scan(now=later), 1)
            self.assertEqual(stall_watchdog.scan(now=later), 0)
            release.set()
            thread.join(5)
        text = "\n".join(logs.output)
        self.assertIn("stalled_request", text)
        self.assertIn("route=medialist/<str:media_type>", text)
        self.assertIn(":view <-", text)
        self.assertNotIn("SECRET", text)
        self.assertEqual(stall_watchdog._requests, {})

    def test_fast_request_is_not_reported(self):
        """A request that finishes before the threshold is never reported."""
        middleware = RequestPerformanceLoggingMiddleware(
            lambda request: HttpResponse("ok")
        )
        middleware(RequestFactory().get("/x"))
        self.assertEqual(stall_watchdog.scan(now=time.monotonic() + 60), 0)

    @override_settings(PERF_STALL_MAX_REPORTS_PER_MINUTE=2)
    def test_report_volume_is_bounded(self):
        """A stall storm logs at most the configured reports per minute."""
        tokens = [stall_watchdog.enter("GET", f"/p{i}") for i in range(5)]
        try:
            with self.assertLogs("app.stall_watchdog", level="WARNING"):
                reported = stall_watchdog.scan(now=time.monotonic() + 60)
            self.assertEqual(reported, 2)
        finally:
            for token in tokens:
                stall_watchdog.leave(token)

    @override_settings(PERF_STALL_WARN_MS=0)
    def test_disabled_registers_nothing(self):
        """A zero threshold keeps the registry untouched."""
        middleware = RequestPerformanceLoggingMiddleware(
            lambda request: HttpResponse("ok")
        )
        middleware(RequestFactory().get("/x"))
        self.assertEqual(stall_watchdog._requests, {})
