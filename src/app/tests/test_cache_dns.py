"""Optional cache DNS must not monopolize request threads during an outage."""

import socket
import ssl
import threading
import time
from unittest import mock

import redis
from django.test import SimpleTestCase, tag
from redis.connection import ConnectionPool, UnixDomainSocketConnection

from app import cache_safety, request_timing

IPV4 = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 6379))]


class CacheDNSResolverTests(SimpleTestCase):
    def setUp(self):
        self.resolver = cache_safety._CacheDNSResolver()

    @tag("slow", "benchmark")
    def test_stalled_job_bounds_first_wait_and_recovers_without_extra_threads(self):
        release = threading.Event()

        def stalled_lookup(*_args):
            release.wait(5)
            return IPV4

        with mock.patch("app.cache_safety.socket.getaddrinfo", side_effect=stalled_lookup) as lookup:
            try:
                started = time.monotonic()
                with self.assertRaises(redis.TimeoutError):
                    self.resolver.resolve("redis", 6379, 0, 0.03)
                self.assertLess(time.monotonic() - started, 0.5)
                pending = self.resolver._pending
                started = time.monotonic()
                for _ in range(10):
                    with self.assertRaises(cache_safety.CacheCoolingDownError):
                        self.resolver.resolve("redis", 6379, 0, 0.03)
                self.assertLess(time.monotonic() - started, 0.1)
                self.assertEqual(lookup.call_count, 1)
                release.set()
                self.assertTrue(pending["event"].wait(1))
                self.assertEqual(self.resolver.resolve("redis", 6379, 0, 0.03), IPV4)
                self.assertIsNone(self.resolver._pending)
                self.assertEqual(lookup.call_count, 1)
            finally:
                release.set()
                if self.resolver._pending:
                    self.resolver._pending["event"].wait(1)

    def test_positive_cache_has_bounded_size_and_expires(self):
        now = [0.0]
        with (
            mock.patch("app.cache_safety.time.monotonic", side_effect=lambda: now[0]),
            mock.patch("app.cache_safety.socket.getaddrinfo", return_value=IPV4) as lookup,
        ):
            for index in range(10):
                self.resolver.resolve(f"redis-{index}", 6379, 0, 1)
            self.assertEqual(len(self.resolver._cache), cache_safety.CACHE_DNS_MAX_ENTRIES)
            self.assertNotIn(("redis-0", 6379, 0), self.resolver._cache)
            self.resolver.resolve("redis-9", 6379, 0, 1)
            self.assertEqual(lookup.call_count, 10)
            now[0] = cache_safety.CACHE_DNS_TTL + 1
            self.resolver.resolve("redis-9", 6379, 0, 1)
            self.assertEqual(lookup.call_count, 11)

    def test_fork_reset_precedes_acquiring_inherited_lock(self):
        inherited_lock = self.resolver._lock
        inherited_lock.acquire()
        try:
            with (
                mock.patch("app.cache_safety.os.getpid", return_value=self.resolver._pid + 1),
                mock.patch("app.cache_safety.socket.getaddrinfo", return_value=IPV4),
            ):
                self.assertEqual(self.resolver.resolve("redis", 6379, 0, 1), IPV4)
            self.assertIsNot(self.resolver._lock, inherited_lock)
        finally:
            inherited_lock.release()

    def test_late_consumption_does_not_refresh_stale_addresses(self):
        completed = threading.Event()
        completed.set()
        self.resolver._pending = {
            "key": ("redis", 6379, 0), "event": completed,
            "error": None, "addresses": IPV4, "completed_at": 0,
        }
        changed = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.2", 6379))]
        with (
            mock.patch("app.cache_safety.time.monotonic", return_value=31),
            mock.patch("app.cache_safety.socket.getaddrinfo", return_value=changed) as lookup,
        ):
            self.assertEqual(self.resolver.resolve("redis", 6379, 0, 1), changed)
        lookup.assert_called_once()

    def test_resolver_errors_preserve_redis_error_contract_and_can_recover(self):
        with mock.patch("app.cache_safety.socket.getaddrinfo", side_effect=[socket.gaierror(-3, "temporary failure"), IPV4]):
            with self.assertRaises(redis.ConnectionError):
                self.resolver.resolve("redis", 6379, 0, 1)
            self.assertEqual(self.resolver.resolve("redis", 6379, 0, 1), IPV4)

    def test_worker_start_failure_does_not_leave_phantom_job(self):
        with mock.patch("app.cache_safety.threading.Thread.start", side_effect=RuntimeError("no resources")):
            with self.assertRaises(redis.ConnectionError):
                self.resolver.resolve("redis", 6379, 0, 1)
        self.assertIsNone(self.resolver._pending)


class CacheDNSConnectionTests(SimpleTestCase):
    def test_pool_retains_url_transport_and_unix_options(self):
        for url, expected in (
            ("redis://localhost:6379/3", cache_safety.CacheConnection),
            ("rediss://localhost:6379/3?ssl_cert_reqs=required", cache_safety.CacheSSLConnection),
            ("unix:///tmp/cache-dns-test.sock?db=3", UnixDomainSocketConnection),
        ):
            with self.subTest(url=url):
                pool = cache_safety.CacheConnectionPool.from_url(url)
                connection = pool.make_connection()
                self.assertIs(type(connection), expected)
                self.assertEqual(connection.db, 3)
                if expected is UnixDomainSocketConnection:
                    self.assertEqual(connection.path, "/tmp/cache-dns-test.sock")  # noqa: S108 -- parsing only, no socket opened
                elif expected is cache_safety.CacheSSLConnection:
                    self.assertEqual(connection.cert_reqs, ssl.CERT_REQUIRED)

    def test_ipv6_scope_keepalive_timeouts_and_timing_are_preserved(self):
        address = ("fe80::1", 6379, 0, 4)
        addresses = [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", address)]
        connection = cache_safety.CacheConnection(
            host="redis", port=6379, socket_connect_timeout=0.5, socket_timeout=0.75,
            socket_keepalive=True, socket_keepalive_options={123: 7},
        )
        sock = mock.Mock()
        tally, token = request_timing.begin()
        try:
            with (
                mock.patch.object(cache_safety._cache_dns, "resolve", return_value=addresses) as resolve,
                mock.patch("app.cache_safety.socket.socket", return_value=sock) as create,
            ):
                self.assertIs(connection._connect(), sock)
            resolve.assert_called_once_with("redis", 6379, 0, 0.5)
            create.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            sock.connect.assert_called_once_with(address)
            self.assertEqual(sock.settimeout.call_args_list, [mock.call(0.5), mock.call(0.75)])
            sock.setsockopt.assert_has_calls([
                mock.call(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
                mock.call(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
                mock.call(socket.IPPROTO_TCP, 123, 7),
            ])
            self.assertEqual(tally["boundary_calls"]["redis_connect"], 1)
            self.assertEqual(tally["boundary_calls"]["redis_dns_wait"], 1)
        finally:
            request_timing.end(token)

    def test_tls_uses_original_hostname_and_verification(self):
        connection = cache_safety.CacheSSLConnection(
            host="redis.example.test", socket_connect_timeout=1,
            ssl_check_hostname=True, ssl_cert_reqs="required",
        )
        sock = mock.Mock()
        context = mock.Mock()
        with (
            mock.patch.object(cache_safety._cache_dns, "resolve", return_value=IPV4),
            mock.patch("app.cache_safety.socket.socket", return_value=sock),
            mock.patch("redis.connection.ssl.create_default_context", return_value=context),
        ):
            self.assertIs(connection._connect(), context.wrap_socket.return_value)
        context.wrap_socket.assert_called_once_with(sock, server_hostname="redis.example.test")
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_failed_socket_is_closed_before_next_address(self):
        broken = mock.Mock()
        broken.connect.side_effect = OSError("unreachable")
        working = mock.Mock()
        connection = cache_safety.CacheConnection(host="redis")
        with (
            mock.patch.object(cache_safety._cache_dns, "resolve", return_value=IPV4 * 2),
            mock.patch("app.cache_safety.socket.socket", side_effect=[broken, working]),
        ):
            self.assertIs(connection._connect(), working)
        broken.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        broken.close.assert_called_once_with()

    def test_plain_pool_keeps_original_redis_failure(self):
        client = cache_safety.CacheRedis(connection_pool=ConnectionPool())
        failure = redis.TimeoutError("read timeout")
        with (
            mock.patch("redis.Redis.execute_command", side_effect=failure),
            self.assertRaises(redis.TimeoutError) as raised,
        ):
            client.get("optional")
        self.assertIs(raised.exception, failure)
