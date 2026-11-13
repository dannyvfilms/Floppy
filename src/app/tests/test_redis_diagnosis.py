"""Tests for naming why Redis could not be reached (#1263)."""

import socket
from unittest import mock

import redis
from django.test import SimpleTestCase
from kombu.exceptions import OperationalError

from app import redis_diagnosis
from app.redis_diagnosis import (
    AUTH,
    DNS,
    OTHER,
    REFUSED,
    TIMEOUT,
    classify_redis_error,
    explain_redis_error,
    queue_failure_message,
    unreachable_detail,
)

# The exact text redis-py raised in #1166, from the Alpine (musl) image.
DNS_TEXT = "Error -2 connecting to redis:6379. Name does not resolve."


def _raised_from(outer, inner):
    """Return ``outer`` as if raised while handling ``inner``.

    redis-py raises its ConnectionError inside the except block for the socket
    error, and Kombu does the same around redis-py, which sets ``__context__``.
    """
    try:
        try:
            raise inner
        except type(inner):
            raise outer  # noqa: B904 - reproducing implicit chaining
    except type(outer) as error:
        return error


class ClassifyRedisErrorTests(SimpleTestCase):
    def test_socket_resolver_failure_is_dns(self):
        self.assertEqual(
            classify_redis_error(socket.gaierror(-2, "Name does not resolve")),
            DNS,
        )

    def test_redis_py_message_alone_is_dns(self):
        self.assertEqual(classify_redis_error(redis.ConnectionError(DNS_TEXT)), DNS)

    def test_glibc_wording_is_dns(self):
        error = redis.ConnectionError(
            "Error -3 connecting to redis:6379. Temporary failure in name resolution."
        )
        self.assertEqual(classify_redis_error(error), DNS)

    def test_kombu_wrapping_redis_wrapping_socket_is_dns(self):
        """The shape an import view actually catches from ``task.delay()``."""
        socket_error = socket.gaierror(-2, "Name does not resolve")
        redis_error = _raised_from(redis.ConnectionError(DNS_TEXT), socket_error)
        kombu_error = _raised_from(OperationalError(DNS_TEXT), redis_error)
        self.assertEqual(classify_redis_error(kombu_error), DNS)

    def test_kombu_message_without_a_chain_is_dns(self):
        """Kombu can re-raise with only the text, so the text must suffice."""
        self.assertEqual(classify_redis_error(OperationalError(DNS_TEXT)), DNS)

    def test_refused_connection(self):
        error = redis.ConnectionError(
            "Error 111 connecting to redis:6379. Connection refused."
        )
        self.assertEqual(classify_redis_error(error), REFUSED)
        self.assertEqual(classify_redis_error(ConnectionRefusedError()), REFUSED)

    def test_timeout(self):
        self.assertEqual(classify_redis_error(redis.TimeoutError("x")), TIMEOUT)
        self.assertEqual(
            classify_redis_error(redis.ConnectionError("Timeout connecting to server")),
            TIMEOUT,
        )

    def test_auth(self):
        self.assertEqual(
            classify_redis_error(redis.AuthenticationError("invalid password")),
            AUTH,
        )

    def test_unrelated_error(self):
        self.assertEqual(classify_redis_error(ValueError("bad pickle")), OTHER)

    def test_a_cycle_in_the_chain_terminates(self):
        first = ValueError("a")
        second = ValueError("b")
        first.__context__ = second
        second.__context__ = first
        self.assertEqual(classify_redis_error(first), OTHER)


class ExplainRedisErrorTests(SimpleTestCase):
    url = "redis://:secret-password@redis:6379/0"

    def test_dns_in_a_container_names_the_shared_network(self):
        with mock.patch("app.preflight.in_container", return_value=True):
            cause, fix = explain_redis_error(redis.ConnectionError(DNS_TEXT), self.url)

        self.assertIn('"redis" does not resolve', cause)
        self.assertIn("network", fix)
        self.assertIn("network_mode", fix)
        self.assertIn(redis_diagnosis.GUIDE_URL, fix)

    def test_dns_outside_a_container_gives_no_docker_advice(self):
        with mock.patch("app.preflight.in_container", return_value=False):
            _cause, fix = explain_redis_error(redis.ConnectionError(DNS_TEXT), self.url)

        self.assertNotIn("Docker", fix)
        self.assertIn("REDIS_URL", fix)

    def test_unexplained_errors_leave_the_callers_wording(self):
        self.assertEqual(explain_redis_error(ValueError("x"), self.url), ("", ""))

    def test_credentials_never_appear(self):
        for error in (
            redis.ConnectionError(DNS_TEXT),
            redis.ConnectionError("Connection refused"),
            redis.TimeoutError("timed out"),
        ):
            with self.subTest(error=error):
                text = " ".join(explain_redis_error(error, self.url))
                text += unreachable_detail(error, self.url) or ""
                self.assertNotIn("secret-password", text)

    def test_ipv6_hosts_keep_their_brackets(self):
        """Found in review. safe_url drops the brackets, which broke the port."""
        detail = unreachable_detail(
            redis.ConnectionError("Connection refused"),
            "redis://:secret@[::1]:6379/0",
        )
        self.assertIn("cannot reach Redis at [::1]:6379", detail)
        self.assertNotIn("secret", detail)

    def test_a_non_redis_broker_is_not_blamed_on_redis(self):
        """Found in review. Celery also supports RabbitMQ."""
        self.assertIsNone(
            unreachable_detail(
                ConnectionRefusedError(),
                "amqp://guest:guest@rabbitmq:5672//",
            )
        )

    def test_unix_socket_urls_name_the_path(self):
        detail = unreachable_detail(
            redis.ConnectionError("Connection refused"),
            "unix:///run/redis/redis.sock",
        )
        self.assertIn("/run/redis/redis.sock", detail)


class QueueFailureMessageTests(SimpleTestCase):
    def test_unreachable_broker_replaces_the_hint(self):
        message = queue_failure_message(
            OperationalError(DNS_TEXT),
            "The import could not be queued.",
            "Check the worker and try again.",
            "redis://redis:6379",
        )

        self.assertTrue(message.startswith("The import could not be queued."))
        self.assertIn("cannot reach Redis at redis:6379", message)
        self.assertIn(redis_diagnosis.GUIDE_SECTION, message)
        self.assertNotIn("worker", message)

    def test_other_failures_keep_the_hint(self):
        message = queue_failure_message(
            ValueError("serializer"),
            "The import could not be queued.",
            "Check the worker and try again.",
            "redis://redis:6379",
        )
        self.assertEqual(
            message,
            "The import could not be queued. Check the worker and try again.",
        )
