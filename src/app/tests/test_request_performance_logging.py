"""Tests for RequestPerformanceLoggingMiddleware."""

import re
import socket
import time
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings

from app import request_timing
from app.middleware import RequestPerformanceLoggingMiddleware
from app.models import Item
from app.providers import pocketcasts
from users.models import User


class RequestPerformanceLoggingMiddlewareTests(TestCase):
    """Verify slow/query-heavy requests are logged and fast ones are not."""

    def setUp(self):
        """Create a request factory."""
        self.factory = RequestFactory()

    def _run(self, view):
        middleware = RequestPerformanceLoggingMiddleware(view)
        return middleware(self.factory.get("/test-path"))

    @override_settings(
        PERF_LOG_ENABLED=True,
        PERF_LOG_SLOW_REQUEST_MS=0,
        PERF_LOG_QUERY_COUNT_THRESHOLD=10_000,
    )
    def test_logs_slow_request(self):
        """A request over the duration threshold is logged."""
        with self.assertLogs("app.middleware", level="INFO") as logs:
            response = self._run(lambda _request: HttpResponse("ok"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("slow_request", logs.output[0])
        self.assertIn("path=/test-path", logs.output[0])

    @override_settings(
        PERF_LOG_ENABLED=True,
        PERF_LOG_SLOW_REQUEST_MS=10_000,
        PERF_LOG_QUERY_COUNT_THRESHOLD=1,
    )
    def test_logs_query_heavy_request(self):
        """A request over the query-count threshold is logged."""

        def view(_request):
            list(Item.objects.all())
            return HttpResponse("ok")

        with self.assertLogs("app.middleware", level="INFO") as logs:
            self._run(view)
        self.assertIn("queries=1", logs.output[0])

    @override_settings(
        PERF_LOG_ENABLED=True,
        PERF_LOG_SLOW_REQUEST_MS=10_000,
        PERF_LOG_QUERY_COUNT_THRESHOLD=10_000,
    )
    def test_fast_request_not_logged(self):
        """A fast, light request is not logged."""
        with self.assertNoLogs("app.middleware", level="INFO"):
            self._run(lambda _request: HttpResponse("ok"))

    @override_settings(PERF_LOG_ENABLED=False, PERF_LOG_SLOW_REQUEST_MS=0)
    def test_disabled_via_setting(self):
        """The middleware is a no-op when disabled."""
        with self.assertNoLogs("app.middleware", level="INFO"):
            response = self._run(lambda _request: HttpResponse("ok"))
        self.assertEqual(response.status_code, 200)


@override_settings(
    PERF_LOG_ENABLED=True,
    PERF_LOG_SLOW_REQUEST_MS=0,
    PERF_LOG_QUERY_COUNT_THRESHOLD=10_000,
)
class RequestTimingBreakdownTests(TestCase):
    def test_sql_profile_normalizes_literals_and_keeps_span_attribution(self):
        tally, token = request_timing.begin()
        try:
            with request_timing.profile_sql() as profile, request_timing.boundary("home_rank"):
                request_timing.record_sql("SELECT id FROM app_episode WHERE id IN (1,2,3) AND notes='private'", 0.01)
                request_timing.record_sql("SELECT id FROM app_episode WHERE id IN (4,5) AND notes='secret'", 0.02)
            rows = list(profile["queries"].values())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["count"], 2)
            self.assertAlmostEqual(rows[0]["cumulative_ms"], 30)
            self.assertAlmostEqual(rows[0]["max_ms"], 20)
            self.assertEqual(rows[0]["span"], "home_rank")
            self.assertNotIn("private", rows[0]["shape"])
            self.assertNotIn("secret", rows[0]["shape"])
        finally:
            request_timing.end(token)

    def test_sql_profile_bounds_distinct_shapes(self):
        with request_timing.profile_sql() as profile:
            for index in range(100):
                request_timing.record_sql(f"SELECT field_{index} FROM app_episode", 0.001)  # noqa: S608 -- inert diagnostic string, never executed
        self.assertEqual(len(profile["queries"]), 64)
        self.assertEqual(profile["overflow_count"], 36)

    """The log line and Server-Timing header say where a request's time went."""

    def setUp(self):
        """Create a request factory and a signed-in user."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="timer", password="pw")

    def _run(self, view, user=None):
        request = self.factory.get("/test-path")
        request.user = user or AnonymousUser()
        with self.assertLogs("app.middleware", level="INFO") as logs:
            response = RequestPerformanceLoggingMiddleware(view)(request)
        return response, logs.output[0]

    @staticmethod
    def _field(line, name):
        return float(re.search(rf"{name}=([0-9.]+)", line).group(1))

    def test_log_line_carries_the_breakdown_fields(self):
        _response, line = self._run(lambda _request: HttpResponse("ok"))

        for name in ("cpu_ms", "db_ms", "provider_ms", "provider_calls", "inflight"):
            self.assertIn(f"{name}=", line)
        self.assertEqual(self._field(line, "inflight"), 1)

    def test_provider_time_is_counted_once_for_nested_calls(self):
        @request_timing.timed_provider_call
        def inner():
            time.sleep(0.03)

        @request_timing.timed_provider_call
        def outer():
            inner()
            inner()

        def view(_request):
            outer()
            return HttpResponse("ok")

        _response, line = self._run(view)

        self.assertEqual(self._field(line, "provider_calls"), 1)
        self.assertGreaterEqual(self._field(line, "provider_ms"), 55)
        self.assertLess(self._field(line, "provider_ms"), 200)

    def test_waiting_is_not_reported_as_cpu(self):
        def view(_request):
            time.sleep(0.05)
            return HttpResponse("ok")

        _response, line = self._run(view)

        self.assertGreaterEqual(self._field(line, "duration_ms"), 50)
        self.assertLess(self._field(line, "cpu_ms"), 40)

    def test_redis_connection_and_dns_are_nested_exclusive_spans(self):
        """Keep TCP work distinct from Redis DNS without counting it twice."""
        from redis.connection import Connection

        network = mock.Mock()
        network.connect.side_effect = lambda *_args: time.sleep(0.02)

        def view(_request):
            with request_timing.boundary("cache"):
                Connection(host="127.0.0.1", port=6379)._connect()
            # Provider and other OS lookups do not add Redis DNS spans.
            socket.getaddrinfo("127.0.0.1", 80)
            return HttpResponse("ok")

        with mock.patch("redis.connection.socket.socket", return_value=network):
            response, line = self._run(view, self.user)
        self.assertGreaterEqual(self._field(line, "redis_connect_ms"), 19)
        self.assertLess(self._field(line, "cache_ms"), 15)
        self.assertIn("redis_dns;dur=", response["Server-Timing"])
        self.assertNotIn("127.0.0.1", line)

    def test_database_time_is_counted(self):
        def view(_request):
            # An empty-table read finishes in under the 0.1 ms the log rounds to,
            # so count to a few hundred thousand to take measurable time.
            with connection.cursor() as cursor:
                cursor.execute(
                    "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n "
                    "WHERE x < 300000) SELECT count(*) FROM n",
                )
                cursor.fetchone()
            return HttpResponse("ok")

        _response, line = self._run(view)

        self.assertEqual(self._field(line, "queries"), 1)
        self.assertGreater(self._field(line, "db_ms"), 0)

    def test_server_timing_header_for_signed_in_users_only(self):
        response, _line = self._run(lambda _request: HttpResponse("ok"), self.user)
        self.assertRegex(
            response["Server-Timing"],
            r"^total;dur=\d+, cpu;dur=[\d.]+, db;dur=[\d.]+, provider;dur=[\d.]+, "
            r"cache;dur=[\d.]+, broker;dur=[\d.]+, db_connect;dur=[\d.]+, "
            r"render;dur=[\d.]+, unclassified;dur=[\d.]+, queries;desc=\"\d+\"$",
        )

        anonymous_response, _line = self._run(lambda _request: HttpResponse("ok"))
        self.assertNotIn("Server-Timing", anonymous_response)

    def test_providers_that_call_requests_directly_are_counted(self):
        def slow_get(*_args, **_kwargs):
            time.sleep(0.03)
            response = mock.Mock()
            response.json.return_value = {"results": []}
            return response

        def view(_request):
            pocketcasts.search("news", 1)
            return HttpResponse("ok")

        with mock.patch("app.providers.pocketcasts.requests.get", slow_get):
            _response, line = self._run(view)

        self.assertEqual(self._field(line, "provider_calls"), 1)
        self.assertGreaterEqual(self._field(line, "provider_ms"), 25)

    def test_recording_outside_a_request_does_nothing(self):
        @request_timing.timed_provider_call
        def call():
            return "result"

        self.assertEqual(call(), "result")

    def test_cache_wait_is_attributed_including_failures(self):
        def slow_get(*_args, **_kwargs):
            time.sleep(0.03)
            raise RuntimeError("test cache failure")

        def view(_request):
            with self.assertRaises(RuntimeError):
                cache.get("timing-test")
            return HttpResponse("ok")

        with mock.patch("django_redis.client.DefaultClient.get", slow_get):
            _response, line = self._run(view)
        self.assertGreaterEqual(self._field(line, "cache_ms"), 25)
        self.assertLess(self._field(line, "unclassified_ms"), 25)

    def test_nested_boundaries_do_not_double_count(self):
        tally, token = request_timing.begin()
        try:
            with request_timing.boundary("broker"):
                with request_timing.boundary("cache"):
                    time.sleep(0.03)
            self.assertGreaterEqual(tally["boundaries"]["cache"], 0.025)
            self.assertLess(tally["boundaries"]["broker"], 0.025)
        finally:
            request_timing.end(token)

    def test_installation_is_idempotent(self):
        from django_redis.cache import RedisCache

        request_timing.install_boundaries()
        wrapped = RedisCache.get
        request_timing.install_boundaries()
        self.assertIs(RedisCache.get, wrapped)

    def test_broker_publication_wait_is_attributed(self):
        from celery import shared_task

        @shared_task
        def probe():
            return None

        def publish(*_args, **_kwargs):
            time.sleep(0.03)
            return mock.Mock()

        def view(_request):
            probe.delay()
            return HttpResponse("ok")

        with override_settings(CELERY_TASK_ALWAYS_EAGER=False), mock.patch(
            "celery.app.base.Celery.send_task", side_effect=publish
        ):
            _response, line = self._run(view)
        self.assertGreaterEqual(self._field(line, "broker_ms"), 25)

    def test_template_rendering_is_attributed(self):
        from django.template import Context, Template

        def render(*_args, **_kwargs):
            time.sleep(0.03)
            return "ok"

        def view(_request):
            return HttpResponse(Template("ok").render(Context()))

        with mock.patch("django.template.base.Template._render", side_effect=render):
            _response, line = self._run(view)
        self.assertGreaterEqual(self._field(line, "render_ms"), 25)

    def test_connection_establishment_is_attributed_before_sql(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper

        original = DatabaseWrapper.get_new_connection

        def connect(database, params):
            time.sleep(0.03)
            return original(database, params)

        def view(_request):
            database = DatabaseWrapper(connection.settings_dict.copy(), "timing-probe")
            try:
                database.connect()
            finally:
                database.close()
            return HttpResponse("ok")

        with mock.patch.object(DatabaseWrapper, "get_new_connection", connect):
            _response, line = self._run(view)
        self.assertGreaterEqual(self._field(line, "db_connect_ms"), 25)

    def test_concurrent_requests_keep_separate_tallies(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        barrier = Barrier(2)

        def collect(name):
            tally, token = request_timing.begin()
            try:
                with request_timing.boundary(name):
                    barrier.wait(timeout=5)
                    time.sleep(0.01)
                return tally["boundaries"]
            finally:
                request_timing.end(token)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(collect, "cache")
            second = executor.submit(collect, "broker")
            self.assertEqual(set(first.result()), {"cache"})
            self.assertEqual(set(second.result()), {"broker"})
