"""Floppy must keep working when Redis does not (issue #521).

The reported failure was a Redis read timeout inside cache.get propagating all
the way out of webhook processing. These tests pin the behaviour that replaced
it: a cache failure degrades to a miss, and the paths that use the cache for
control flow rather than caching resolve it deliberately.
"""

from contextvars import Context
from datetime import timedelta
from socketserver import BaseRequestHandler, ThreadingTCPServer
from threading import Event, Thread
from time import monotonic
from unittest import mock

import redis
from django.test import RequestFactory, SimpleTestCase, TestCase, tag
from django.utils import timezone

from app import backfill_queue, interactive_requests, tasks_providers
from app.cache_safety import (
    CacheConnectionPool,
    CacheCooldownLogFilter,
    CacheCoolingDownError,
    CacheRedis,
)
from app.interactive_requests import interactive_request_active
from app.models import Item, MediaTypes, Sources
from app.providers import services


class CacheCooldownTests(SimpleTestCase):
    """One connection failure must not become hundreds of timed waits."""

    def test_requests_during_cooldown_do_not_extend_it(self):
        """A steady flow of cache reads still permits a recovery probe."""
        pool = CacheConnectionPool()
        client = CacheRedis(connection_pool=pool)
        clock = [10]
        with (
            mock.patch("app.cache_safety.time.monotonic", side_effect=lambda: clock[0]),
            mock.patch("redis.connection.Connection.connect", side_effect=redis.ConnectionError("dns failure")) as connect,
        ):
            for now in (10, 11, 12):
                clock[0] = now
                with self.assertRaises(redis.ConnectionError):
                    client.get("optional-data")
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(pool._unavailable_until, 14)

    def test_strict_backend_raises_and_optional_backend_returns_default(self):
        """No swallowed failure is mistaken for an acquired cache lock."""
        from django_redis.cache import RedisCache
        from django_redis.exceptions import ConnectionInterrupted

        for ignore in (True, False):
            backend = RedisCache("redis://unused:6379/15", {"OPTIONS": {"IGNORE_EXCEPTIONS": ignore}})
            failure = ConnectionInterrupted(connection=None)
            failure.__cause__ = redis.ConnectionError("cache unavailable")
            with mock.patch.object(backend.client, "get", side_effect=failure):
                if ignore:
                    self.assertEqual(backend.get("optional", "fallback"), "fallback")
                else:
                    with self.assertRaises(redis.ConnectionError):
                        backend.get("optional")

    def test_command_failure_cools_down_pool_and_reset_clears_it(self):
        """A connected socket's timeout also avoids repeated waits."""
        pool = CacheConnectionPool()
        client = CacheRedis(connection_pool=pool)
        with mock.patch("redis.Redis.execute_command", side_effect=redis.TimeoutError("read timeout")):
            with self.assertRaises(redis.TimeoutError):
                client.get("optional")
        self.assertGreater(pool._unavailable_until, 0)
        pool.reset()
        self.assertEqual(pool._unavailable_until, 0)

    def test_only_synthetic_outage_tracebacks_are_suppressed(self):
        """Retain genuine Redis failures for diagnosis."""
        from django_redis.exceptions import ConnectionInterrupted

        filter_ = CacheCooldownLogFilter()
        for error, expected in ((CacheCoolingDownError("cooldown"), False), (redis.TimeoutError("timeout"), True)):
            wrapped = ConnectionInterrupted(connection=None)
            wrapped.__cause__ = error
            self.assertEqual(filter_.filter(mock.Mock(exc_info=(type(wrapped), wrapped, None))), expected)

    @tag("slow", "benchmark")
    def test_half_dead_server_only_consumes_one_socket_timeout(self):
        """Bound repeated cache attempts against a TCP server that never replies."""
        stop = Event()
        connections = []

        class SilentRedis(BaseRequestHandler):
            def handle(self):
                connections.append(1)
                stop.wait(5)

        with ThreadingTCPServer(("127.0.0.1", 0), SilentRedis) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            pool = CacheConnectionPool(
                host="127.0.0.1", port=server.server_address[1],
                socket_timeout=0.05, socket_connect_timeout=0.05,
                retry_on_timeout=False,
            )
            client = CacheRedis(connection_pool=pool)
            try:
                started = monotonic()
                for _ in range(100):
                    with self.assertRaises((redis.ConnectionError, redis.TimeoutError)):
                        client.get("optional")
                elapsed = monotonic() - started
                self.assertEqual(len(connections), 1)
                self.assertGreaterEqual(elapsed, 0.04)
                self.assertLess(elapsed, 1)
            finally:
                stop.set()
                pool.disconnect()
                server.shutdown()
                thread.join(timeout=2)


class CachedSessionOutageTests(TestCase):
    """Cache degradation must still use signed, unexpired database sessions."""

    def test_unavailable_cache_preserves_valid_session_but_rejects_expired_session(self):
        """Never synthesize authenticated state when Redis cannot answer."""
        from django.contrib.sessions.backends.cached_db import SessionStore
        from django.contrib.sessions.models import Session
        from django.core.cache import cache

        store = SessionStore()
        store["_auth_user_id"] = "42"
        store.save()
        key = store.session_key
        with (
            mock.patch.object(cache, "get", return_value=None),
            mock.patch.object(cache, "set", return_value=None),
        ):
            self.assertEqual(SessionStore(key).load()["_auth_user_id"], "42")
            Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(seconds=1))
            self.assertEqual(SessionStore(key).load(), {})


class InteractiveMarkerTests(SimpleTestCase):
    """The marker that background tasks yield to."""

    def setUp(self):
        """Build requests without requiring the full middleware stack."""
        self.request_factory = RequestFactory()

    def test_probe_paths_do_not_count_as_interactive_requests(self):
        """Health and liveness probes must not defer maintenance forever."""
        for path in ("/health/", "/health/full/", "/ping/"):
            for method in ("get", "head"):
                with self.subTest(path=path, method=method):
                    request = getattr(self.request_factory, method)(
                        path,
                        HTTP_ACCEPT="*/*",
                    )
                    self.assertFalse(
                        interactive_requests.should_mark_interactive_request(request),
                    )

    def test_api_requests_do_not_count_as_interactive_requests(self):
        """Machine API traffic is separate from browser activity."""
        request = self.request_factory.get(
            "/api/v1/history/",
            HTTP_ACCEPT="*/*",
        )

        self.assertFalse(
            interactive_requests.should_mark_interactive_request(request),
        )

    def test_html_and_htmx_requests_count_as_interactive_requests(self):
        """Real browser navigation and htmx requests still defer maintenance."""
        html_request = self.request_factory.get(
            "/history/",
            HTTP_ACCEPT="text/html",
        )
        htmx_request = self.request_factory.get(
            "/history/fragment/",
            HTTP_ACCEPT="*/*",
            HTTP_HX_REQUEST="true",
        )

        self.assertTrue(
            interactive_requests.should_mark_interactive_request(html_request),
        )
        self.assertTrue(
            interactive_requests.should_mark_interactive_request(htmx_request),
        )

    def test_unavailable_cache_reports_no_interactive_request(self):
        """True would defer every background task for the whole outage."""
        with mock.patch.object(
            interactive_requests.cache,
            "get",
            side_effect=redis.exceptions.TimeoutError("Timeout reading from redis"),
        ):
            self.assertFalse(interactive_request_active())

    def test_ignored_exception_none_also_reports_no_interactive_request(self):
        """IGNORE_EXCEPTIONS returns None rather than raising."""
        with mock.patch.object(interactive_requests.cache, "get", return_value=None):
            self.assertFalse(interactive_request_active())

    def test_it_never_raises_into_cooperative_run(self):
        """CooperativeRun.iter calls this outside the per-item try/except."""
        from app.task_cooperation import CooperativeRun

        with mock.patch.object(
            interactive_requests.cache,
            "get",
            side_effect=redis.exceptions.ConnectionError("refused"),
        ):
            run = CooperativeRun("test")
            self.assertEqual(list(run.iter([1, 2, 3])), [1, 2, 3])


class RateLimiterDegradationTests(SimpleTestCase):
    """Redis backs the shared rate-limit bucket used on every provider call.

    A bucket built while Redis was reachable still does live Redis I/O on
    every subsequent request (#1166's actual crash), unlike the
    construction-time fallback in build_limiter_session().
    """

    def test_redis_failure_falls_back_to_a_rate_limited_session(self):
        """A live Redis outage must not turn into a 500 for the caller."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {"ok": True}

        with (
            mock.patch.object(
                services.session,
                "get",
                side_effect=redis.exceptions.ConnectionError("refused"),
            ),
            mock.patch.object(
                services._fallback_session,
                "get",
                return_value=mock_response,
            ) as mock_fallback,
        ):
            result = services.api_request(
                Sources.TVDB.value,
                "GET",
                "https://example.test/api",
                params={"q": "1"},
            )

        self.assertEqual(result, {"ok": True})
        mock_fallback.assert_called_once()
        self.assertEqual(
            mock_fallback.call_args.kwargs["url"], "https://example.test/api"
        )

    def test_redis_failure_reuses_the_same_fallback_session_across_calls(self):
        """The fallback's own limit must persist, not reset, across calls."""
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {"ok": True}

        with (
            mock.patch.object(
                services.session,
                "get",
                side_effect=redis.exceptions.ConnectionError("refused"),
            ),
            mock.patch.object(
                services._fallback_session,
                "get",
                return_value=mock_response,
            ) as mock_fallback,
        ):
            services.api_request(
                Sources.TVDB.value, "GET", "https://example.test/api"
            )
            services.api_request(
                Sources.TVDB.value, "GET", "https://example.test/api"
            )

        self.assertEqual(mock_fallback.call_count, 2)

    def test_non_redis_request_errors_still_raise_provider_api_error(self):
        """The new fallback must not swallow genuine request failures."""
        with mock.patch.object(
            services.session,
            "get",
            side_effect=services.requests.exceptions.ConnectionError("dns fail"),
        ):
            with self.assertRaises(services.ProviderAPIError):
                services.api_request(
                    Sources.TVDB.value,
                    "GET",
                    "https://example.test/api",
                )


class BackfillQueueDegradationTests(TestCase):
    """The queue must report unavailability rather than dropping work."""

    def setUp(self):
        """Start each test from an empty queue."""
        backfill_queue.clear(
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY,
        )

    def test_enqueue_reports_failure_when_redis_is_down(self):
        """A False return is what lets the caller dispatch directly instead."""
        with mock.patch.object(
            backfill_queue,
            "_client",
            return_value=mock.Mock(
                pipeline=mock.Mock(
                    side_effect=redis.exceptions.ConnectionError("refused"),
                ),
            ),
        ):
            queued = backfill_queue.enqueue(
                "q",
                "s",
                [1, 2],
                ttl=60,
                drain_task=mock.Mock(),
            )
        self.assertFalse(queued)

    @mock.patch("app.tasks_providers.populate_provider_data_for_items.apply_async")
    @mock.patch("app.tasks_providers.populate_provider_backfill_queue.apply_async")
    def test_items_are_dispatched_directly_when_the_queue_is_unavailable(
        self,
        mock_drain,
        mock_direct,
    ):
        """The fallback used to be dead code, silently dropping the items."""
        item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Unavailable Queue Movie",
        )

        with mock.patch.object(backfill_queue, "enqueue", return_value=False):
            queued = tasks_providers.enqueue_provider_backfill_items([item.id])

        self.assertEqual(queued, 1)
        mock_direct.assert_called_once()
        self.assertEqual(mock_direct.call_args.kwargs["args"], [[item.id]])
        mock_drain.assert_not_called()

    def test_take_reports_no_work_rather_than_raising(self):
        """A drain task must not crash when Redis goes away mid-run."""
        with mock.patch.object(
            backfill_queue,
            "_client",
            return_value=mock.Mock(
                spop=mock.Mock(side_effect=redis.exceptions.TimeoutError("timeout")),
            ),
        ):
            batch, more = backfill_queue.take("q", "s", 50)
        self.assertEqual(batch, [])
        self.assertFalse(more)


class BackfillQueueBehaviourTests(TestCase):
    """The set-backed queue's own semantics."""

    QUEUE = "test_backfill_queue"
    SCHEDULED = "test_backfill_scheduled"

    def setUp(self):
        """Start each test from an empty queue."""
        backfill_queue.clear(self.QUEUE, self.SCHEDULED)

    def test_enqueue_deduplicates_without_reading_the_whole_queue(self):
        """The set is what removes the O(N) read-modify-write per batch."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [1, 2, 3], ttl=60, drain_task=drain
        )
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [3, 4], ttl=60, drain_task=drain
        )

        self.assertEqual(backfill_queue.members(self.QUEUE), {1, 2, 3, 4})
        self.assertEqual(backfill_queue.depth(self.QUEUE), 4)

    def test_only_the_first_enqueue_schedules_a_drain(self):
        """The marker keeps a burst of enqueues from queueing a drain each."""
        drain = mock.Mock()
        for _ in range(5):
            backfill_queue.enqueue(
                self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
            )
        drain.apply_async.assert_called_once()

    def test_take_removes_the_batch_and_reports_whether_more_remain(self):
        """The drain has to know whether to schedule itself again."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, range(10), ttl=60, drain_task=drain
        )

        batch, more = backfill_queue.take(self.QUEUE, self.SCHEDULED, 4)
        self.assertEqual(len(batch), 4)
        self.assertTrue(more)
        self.assertEqual(backfill_queue.depth(self.QUEUE), 6)

        _, more = backfill_queue.take(self.QUEUE, self.SCHEDULED, 100)
        self.assertFalse(more)
        self.assertEqual(backfill_queue.depth(self.QUEUE), 0)

    def test_take_holds_the_queue_claim_while_a_batch_runs(self):
        """A concurrent enqueue must not start a drain alongside the running one."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [1, 2, 3], ttl=60, drain_task=drain
        )
        drain.reset_mock()

        batch, _ = backfill_queue.take(self.QUEUE, self.SCHEDULED, 2)
        self.assertEqual(len(batch), 2)
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [4], ttl=60, drain_task=drain
        )
        drain.apply_async.assert_not_called()

    def test_drain_schedules_the_continuation_only_after_the_batch(self):
        """The next drain must not start while this one still fetches metadata."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, range(4), ttl=60, drain_task=drain
        )
        drain.reset_mock()

        with backfill_queue.drain(
            self.QUEUE, self.SCHEDULED, 2, drain_task=drain
        ) as batch:
            self.assertEqual(len(batch), 2)
            drain.apply_async.assert_not_called()

        drain.apply_async.assert_called_once_with(countdown=10, kwargs={})

    def test_drain_releases_the_claim_when_the_queue_is_empty(self):
        """An empty queue must be claimable again by the next enqueue."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
        )
        drain.reset_mock()

        with backfill_queue.drain(
            self.QUEUE, self.SCHEDULED, 10, drain_task=drain
        ) as batch:
            self.assertEqual(batch, [1])
        drain.apply_async.assert_not_called()

        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [2], ttl=60, drain_task=drain
        )
        drain.apply_async.assert_called_once()

    def test_drain_picks_up_work_enqueued_while_it_ran(self):
        """Work that lands mid-batch is drained after it, not lost or doubled."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
        )
        drain.reset_mock()

        with backfill_queue.drain(
            self.QUEUE, self.SCHEDULED, 10, drain_task=drain
        ) as batch:
            self.assertEqual(batch, [1])
            backfill_queue.enqueue(
                self.QUEUE, self.SCHEDULED, [2], ttl=60, drain_task=drain
            )
            drain.apply_async.assert_not_called()
        drain.apply_async.assert_called_once()

    def test_string_members_survive_the_round_trip(self):
        """Episode season keys are encoded tokens, not integers."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE,
            self.SCHEDULED,
            ["tmdb:1234:2", "tmdb:5678:1"],
            ttl=60,
            drain_task=drain,
        )
        batch, _ = backfill_queue.take(self.QUEUE, self.SCHEDULED, 10, coerce=str)
        self.assertEqual(set(batch), {"tmdb:1234:2", "tmdb:5678:1"})

    def test_keys_are_namespaced_by_redis_prefix(self):
        """Two instances sharing a Redis must not share backfill queues."""
        with self.settings(REDIS_PREFIX="inst_a"):
            self.assertEqual(backfill_queue.namespaced("q"), "inst_a:q")
        with self.settings(REDIS_PREFIX=None):
            self.assertEqual(backfill_queue.namespaced("q"), "q")

    def test_deferred_publication_persists_members_without_an_import_sized_buffer(self):
        drain = mock.Mock()
        with backfill_queue.defer_backfill_publication():
            for member in range(1000):
                backfill_queue.enqueue(
                    self.QUEUE, self.SCHEDULED, [member], ttl=60, drain_task=drain
                )
            self.assertEqual(backfill_queue.depth(self.QUEUE), 1000)
            self.assertEqual(len(backfill_queue._deferred_drains.get()), 1)
            drain.apply_async.assert_not_called()
        drain.apply_async.assert_called_once_with(countdown=10, kwargs={})

    def test_nested_scope_only_publishes_on_outer_exit(self):
        drain = mock.Mock()
        with backfill_queue.defer_backfill_publication():
            with backfill_queue.defer_backfill_publication():
                backfill_queue.enqueue(
                    self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
                )
            drain.apply_async.assert_not_called()
        drain.apply_async.assert_called_once()

    def test_marker_expiration_during_a_long_import_does_not_publish_again(self):
        drain = mock.Mock()
        with backfill_queue.defer_backfill_publication():
            for member in range(5):
                # Model the 30-second marker expiring between slow batches.
                backfill_queue.clear(self.SCHEDULED)
                backfill_queue.enqueue(
                    self.QUEUE, self.SCHEDULED, [member], ttl=60, drain_task=drain
                )
            drain.apply_async.assert_not_called()
        drain.apply_async.assert_called_once()
        self.assertEqual(backfill_queue.members(self.QUEUE), set(range(5)))

    def test_exception_still_publishes_persisted_work(self):
        drain = mock.Mock()
        with self.assertRaisesMessage(ValueError, "import failed"):
            with backfill_queue.defer_backfill_publication():
                backfill_queue.enqueue(
                    self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
                )
                raise ValueError("import failed")
        drain.apply_async.assert_called_once()
        self.assertEqual(backfill_queue.members(self.QUEUE), {1})
        self.assertIsNone(backfill_queue._deferred_drains.get())

    def test_broker_failure_does_not_mask_import_failure_or_skip_other_queues(self):
        failing = mock.Mock()
        failing.apply_async.side_effect = RuntimeError("broker unavailable")
        healthy = mock.Mock()
        with (
            self.assertLogs("app.backfill_queue", level="ERROR"),
            self.assertRaisesMessage(ValueError, "import failed"),
        ):
            with backfill_queue.defer_backfill_publication():
                backfill_queue.enqueue(
                    self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=failing
                )
                backfill_queue.enqueue(
                    self.QUEUE,
                    self.SCHEDULED + ":other",
                    [2],
                    ttl=60,
                    drain_task=healthy,
                )
                raise ValueError("import failed")
        self.addCleanup(backfill_queue.clear, self.SCHEDULED + ":other")
        healthy.apply_async.assert_called_once()
        self.assertEqual(backfill_queue.members(self.QUEUE), {1, 2})

    def test_an_independent_context_keeps_normal_publication(self):
        drain = mock.Mock()
        with backfill_queue.defer_backfill_publication():
            Context().run(
                backfill_queue.enqueue,
                self.QUEUE,
                self.SCHEDULED,
                [1],
                ttl=60,
                drain_task=drain,
            )
            drain.apply_async.assert_called_once()

    def test_unavailable_redis_does_not_claim_work_was_persisted(self):
        drain = mock.Mock()
        with (
            backfill_queue.defer_backfill_publication(),
            mock.patch.object(backfill_queue, "_client", return_value=None),
        ):
            self.assertFalse(
                backfill_queue.enqueue(
                    self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
                )
            )
        drain.apply_async.assert_not_called()

    def test_descriptor_bound_overflow_publishes_normally(self):
        drain = mock.Mock()
        with (
            mock.patch.object(backfill_queue, "MAX_DEFERRED_DRAINS", 0),
            backfill_queue.defer_backfill_publication(),
        ):
            backfill_queue.enqueue(
                self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
            )
            drain.apply_async.assert_called_once()
