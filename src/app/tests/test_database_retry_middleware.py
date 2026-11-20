"""A locked database is never retried by re-running the view."""

from unittest.mock import Mock

from django.db import OperationalError
from django.test import RequestFactory, SimpleTestCase

from app.middleware import DatabaseRetryMiddleware


class DatabaseRetryMiddlewareTests(SimpleTestCase):
    """Each lock error already waited out SQLite's busy timeout."""

    def test_lock_error_runs_the_view_once_and_reaches_process_exception(self):
        error = OperationalError("database is locked")
        get_response = Mock(side_effect=error)
        middleware = DatabaseRetryMiddleware(get_response)
        request = RequestFactory().get("/")

        with self.assertRaises(OperationalError):
            middleware(request)

        self.assertEqual(get_response.call_count, 1)
        response = middleware.process_exception(request, error)
        self.assertEqual(response.status_code, 503)
