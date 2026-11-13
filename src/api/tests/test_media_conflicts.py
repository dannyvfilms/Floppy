import json
import sqlite3
from types import SimpleNamespace
from unittest import TestCase

from django.db import IntegrityError, OperationalError
from django.test import override_settings

from api.middleware import ApiJsonErrorMiddleware, is_tracked_media_unique_error


class ApiTrackedMediaConflictTests(TestCase):
    """Duplicate tracked-media writes must be stable across database backends."""

    def setUp(self):
        self.middleware = ApiJsonErrorMiddleware(lambda request: None)
        self.request = SimpleNamespace(path="/api/v1/media/tv", method="POST")

    def test_sqlite_user_item_duplicate_is_recognized(self):
        error = IntegrityError(
            "UNIQUE constraint failed: app_tv.user_id, app_tv.item_id",
        )

        self.assertTrue(is_tracked_media_unique_error(error))

        response = self.middleware.process_exception(self.request, error)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content),
            {"detail": "Conflict. Media is already tracked."},
        )

    def test_postgresql_named_duplicate_is_recognized(self):
        cause = RuntimeError(
            'duplicate key value violates unique constraint "app_tv_unique_item_user"',
        )
        cause.diag = SimpleNamespace(constraint_name="app_tv_unique_item_user")
        error = IntegrityError("duplicate tracked media")
        error.__cause__ = cause

        self.assertTrue(is_tracked_media_unique_error(error))

        response = self.middleware.process_exception(self.request, error)

        self.assertEqual(response.status_code, 409)

    @override_settings(DEBUG=False)
    def test_unrelated_integrity_error_stays_internal_server_error(self):
        error = IntegrityError("FOREIGN KEY constraint failed")

        self.assertFalse(is_tracked_media_unique_error(error))

        response = self.middleware.process_exception(self.request, error)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            json.loads(response.content),
            {"detail": "Internal server error."},
        )

    def test_duplicate_outside_media_collection_is_not_reclassified(self):
        request = SimpleNamespace(path="/api/v1/lists", method="POST")
        error = IntegrityError(
            "UNIQUE constraint failed: app_tv.user_id, app_tv.item_id",
        )

        response = self.middleware.process_exception(request, error)

        self.assertEqual(response.status_code, 500)


class ApiDatabaseContentionTests(TestCase):
    """A locked database must be distinguishable from a bad request."""

    def setUp(self):
        self.middleware = ApiJsonErrorMiddleware(lambda request: None)
        self.request = SimpleNamespace(path="/api/v1/media/game", method="POST")

    def test_lock_failure_returns_machine_readable_503(self):
        error = OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY

        response = self.middleware.process_exception(self.request, error)

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.content)
        self.assertEqual(payload["code"], "DATABASE_BUSY")
        # An unsafe POST is never advertised as safe to replay.
        self.assertFalse(payload["retryable"])
        self.assertNotIn("retry_after", payload)
        self.assertNotIn("Retry-After", response)
        self.assertIn("detail", payload)

    def test_safe_get_advertises_a_retry_delay(self):
        request = SimpleNamespace(path="/api/v1/media/movie", method="GET")
        error = OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY

        response = self.middleware.process_exception(request, error)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "5")
        payload = json.loads(response.content)
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["retry_after"], 5)

    def test_invalid_input_is_not_a_database_busy_error(self):
        response = self.middleware.process_exception(self.request, ValueError("bad"))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.content), {"detail": "Internal server error."})
