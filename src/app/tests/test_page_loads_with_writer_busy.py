"""A page load does not wait for SQLite's writer to save derived data.

Each test holds the write lock from a second connection, as an import or a
background job would, and requests a page. The database is a WAL file with
``transaction_mode=IMMEDIATE`` and a five second busy timeout, so a page that
waits for the lock fails its time bound by a wide margin.

Rollback-journal mode, which Floppy falls back to on SQLite builds with the
WAL-reset bug, is not covered: there a committing writer can block readers too.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.db import OperationalError, connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from app import db_retry
from app.benchmark_data import EPOCH, build_dataset
from app.discover import service as discover_service
from app.middleware import DatabaseRetryMiddleware
from app.models import DiscoverRowCache, DiscoverTasteProfile, MediaTypes
from app.tests.sqlite_writes import (
    copy_database_to_file,
    hold_write_lock,
    use_database_file,
)
from integrations.models import IntegrationToken
from users.home_screen import ensure_home_screen_rows
from users.models import User

BUSY_TIMEOUT_SECONDS = 5.0
# Well under the busy timeout, with room for a slow CI host.
PROMPT_SECONDS = 1.0


def _busy_timeout_ms() -> int:
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA busy_timeout")
        return int(cursor.fetchone()[0])


@skipUnless(
    connection.vendor == "sqlite",
    "Reproduces SQLite's single write lock; PostgreSQL has no equivalent.",
)
class PageLoadsWithWriterBusyTests(TestCase):
    """Discover and token-authenticated requests while another writer holds on."""

    @classmethod
    def setUpClass(cls):
        """Build the library once, in a database file the tests copy."""
        for patcher in (
            patch("django.utils.timezone.now", return_value=EPOCH),
            # No provider is reachable, as on an offline host.
            patch(
                "requests.sessions.Session.request",
                side_effect=requests.ConnectionError("offline in this test"),
            ),
            # Tests run tasks inline; a queued task is not part of the page.
            patch("celery.app.task.Task.apply_async", return_value=None),
        ):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.directory = Path(directory.name)
        cls.template = cls.directory / "template.sqlite3"
        # Before TestCase opens its transaction: see copy_database_to_file.
        copy_database_to_file(cls.template)
        with use_database_file(cls.template):
            build_dataset(100, 1729)
            cls.user = User.objects.get(username="bench-user-1")
            ensure_home_screen_rows(cls.user)
        super().setUpClass()

    def setUp(self):
        """Start cold, on this test's own copy of the database file."""
        cache.clear()
        self.database_path = self.directory / f"{self._testMethodName}.sqlite3"
        shutil.copy(self.template, self.database_path)
        database = use_database_file(
            self.database_path, busy_timeout_seconds=BUSY_TIMEOUT_SECONDS
        )
        database.__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        self.client.force_login(self.user)

    def _timed_get(self, path, **headers):
        started = time.perf_counter()
        response = self.client.get(path, headers=headers or None)
        return response, time.perf_counter() - started

    @staticmethod
    def _row_keys(response):
        return [row.key for row in response.context["rows"]]

    def test_discover_serves_its_rows_without_saving_them(self):
        unblocked = self.client.get("/discover")
        expected_keys = self._row_keys(unblocked)
        self.assertTrue(expected_keys)
        self.assertTrue(DiscoverRowCache.objects.exists())
        DiscoverRowCache.objects.all().delete()
        DiscoverTasteProfile.objects.all().delete()
        cache.clear()

        with (
            hold_write_lock(self.database_path),
            self.assertLogs("app.discover", level="WARNING") as logs,
        ):
            response, elapsed = self._timed_get("/discover")

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, PROMPT_SECONDS)
        self.assertEqual(self._row_keys(response), expected_keys)
        self.assertFalse(DiscoverRowCache.objects.exists())
        self.assertFalse(DiscoverTasteProfile.objects.exists())
        output = "\n".join(logs.output)
        self.assertIn("discover_profile_cache_write_skipped", output)
        self.assertIn("discover_row_cache_write_failed", output)
        # The connection is reused by later requests: the short wait is gone.
        self.assertEqual(_busy_timeout_ms(), int(BUSY_TIMEOUT_SECONDS * 1000))

    def test_a_skipped_save_does_not_make_later_page_loads_rebuild(self):
        with hold_write_lock(self.database_path):
            self.client.get("/discover")
            with patch.object(
                discover_service,
                "_build_and_cache_row",
                wraps=discover_service._build_and_cache_row,
            ) as build:
                response, elapsed = self._timed_get("/discover")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._row_keys(response))
        self.assertLess(elapsed, PROMPT_SECONDS)
        build.assert_not_called()

    def test_work_outside_a_page_load_still_waits_and_saves(self):
        """A refresh task keeps the full wait, so its save lands."""
        media_type = MediaTypes.MOVIE.value
        row_keys = [row.key for row in discover_service.get_rows(media_type)][:1]

        with hold_write_lock(self.database_path, seconds=0.4):
            started = time.perf_counter()
            discover_service.refresh_rows_for_user(self.user, media_type, row_keys)
            elapsed = time.perf_counter() - started

        self.assertGreater(elapsed, 0.3)
        self.assertTrue(
            DiscoverRowCache.objects.filter(
                user=self.user, media_type=media_type, row_key=row_keys[0]
            ).exists()
        )
        self.assertTrue(
            DiscoverTasteProfile.objects.filter(
                user=self.user, media_type=media_type
            ).exists()
        )

    def test_token_request_skips_the_last_used_touch(self):
        token, raw_token = IntegrationToken.generate(self.user, "busy-writer")
        self.client.logout()
        headers = {"authorization": f"Bearer {raw_token}"}

        with hold_write_lock(self.database_path):
            response, elapsed = self._timed_get("/api/v1/home/", **headers)

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, PROMPT_SECONDS)
        token.refresh_from_db()
        self.assertIsNone(token.last_used_at)
        self.assertEqual(_busy_timeout_ms(), int(BUSY_TIMEOUT_SECONDS * 1000))

        # With the writer gone, the next request records the use.
        self.client.get("/api/v1/home/", headers=headers)
        token.refresh_from_db()
        self.assertEqual(token.last_used_at, EPOCH)

    def test_api_lock_error_is_a_retryable_503(self):
        """What a native client sees when a view does hit a lock error."""
        with patch(
            "api.fork_views_discover.HomeView.get",
            side_effect=OperationalError("database is locked"),
        ):
            response = self.client.get("/api/v1/home/")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["code"], "DATABASE_BUSY")
        self.assertTrue(body["retryable"])
        self.assertEqual(response["Retry-After"], str(body["retry_after"]))


class ReadRequestMarkerTests(TestCase):
    """Only GET and HEAD requests are page loads."""

    def test_marker_follows_the_request_method(self):
        seen = {}

        def view(request):
            seen[request.method] = db_retry.in_read_request()
            return HttpResponse()

        middleware = DatabaseRetryMiddleware(view)
        factory = RequestFactory()
        middleware(factory.get("/"))
        middleware(factory.head("/"))
        middleware(factory.post("/"))

        self.assertEqual(seen, {"GET": True, "HEAD": True, "POST": False})
        self.assertFalse(db_retry.in_read_request())
