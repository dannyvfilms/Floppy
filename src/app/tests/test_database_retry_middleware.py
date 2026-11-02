"""A locked database is retried once per request, not five times."""

import contextlib
from unittest.mock import Mock, patch

from django.db import DatabaseError, OperationalError
from django.test import RequestFactory, SimpleTestCase

from app.middleware import DatabaseRetryMiddleware


@patch("app.middleware.time.sleep")
class DatabaseRetryMiddlewareTests(SimpleTestCase):
    """Each lock error already waited out SQLite's busy timeout."""

    def _run(self, error, path="/"):
        get_response = Mock(side_effect=error)
        middleware = DatabaseRetryMiddleware(get_response)
        with contextlib.suppress(DatabaseError):
            middleware(RequestFactory().get(path))
        return get_response.call_count

    def test_lock_error_is_retried_once(self, _sleep):
        calls = self._run(OperationalError("database is locked"))

        self.assertEqual(calls, 2)

    def test_disk_io_error_keeps_its_retries(self, _sleep):
        calls = self._run(OperationalError("disk I/O error"))

        self.assertEqual(calls, 6)
