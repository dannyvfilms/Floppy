"""Saved choices and provider cache saves never hold a page load."""

from unittest.mock import patch

from django.db import OperationalError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from app.discover import cache_repo
from app.middleware import DatabaseRetryMiddleware
from users.models import User


class DeferredPreferenceSaveTests(TestCase):
    """A choice made on a GET is saved once the response has gone out."""

    def setUp(self):
        self.user = User.objects.create_user(username="pref", password="x")

    def _get(self, view):
        response = DatabaseRetryMiddleware(view)(RequestFactory().get("/"))
        self.user.refresh_from_db()
        return response

    def test_get_saves_after_the_response_is_closed(self):
        def view(_request):
            self.assertEqual(
                self.user.update_preference("last_search_type", "movie"), "movie"
            )
            stored = User.objects.get(pk=self.user.pk).last_search_type
            self.assertNotEqual(stored, "movie")  # not yet written
            return HttpResponse()

        response = self._get(view)
        self.assertNotEqual(self.user.last_search_type, "movie")
        response.close()
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_search_type, "movie")

    def test_a_busy_writer_after_the_response_only_drops_the_choice(self):
        def view(_request):
            self.user.update_preference("last_search_type", "movie")
            return HttpResponse()

        response = self._get(view)
        with patch(
            "users.models.User.objects.filter",
            side_effect=OperationalError("database is locked"),
        ):
            response.close()  # must not raise

    def test_outside_a_page_load_it_saves_at_once(self):
        self.user.update_preference("last_search_type", "movie")
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_search_type, "movie")


class ProviderCacheSaveTests(TestCase):
    def test_lock_error_does_not_lose_the_fetched_payload(self):
        with patch(
            "app.discover.cache_repo.DiscoverApiCache.objects.update_or_create",
            side_effect=OperationalError("database is locked"),
        ):
            cache_repo.set_api_cache(
                "tmdb", "/x", {}, {"a": 1}, ttl_seconds=60
            )  # no raise

    def test_other_database_errors_still_raise(self):
        with (
            patch(
                "app.discover.cache_repo.DiscoverApiCache.objects.update_or_create",
                side_effect=OperationalError("no such table"),
            ),
            self.assertRaises(OperationalError),
        ):
            cache_repo.set_api_cache("tmdb", "/x", {}, {"a": 1}, ttl_seconds=60)
