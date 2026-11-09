from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Game, Item, MediaTypes, Sources
from app.providers import credentials, services
from app.tasks_igdb_ratings import _populate_igdb_ratings_for_items


class IgdbRatingsBackfillScopeTests(TestCase):
    """The backfill runs with no request, so it must pick up a user's own key."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="g", password="x")
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Hades",
            image="http://example.com/image.jpg",
        )
        Game.objects.create(item=self.item, user=self.user, status="Planning")

    def test_fetch_runs_in_tracking_users_scope(self):
        seen = []

        def fake_metadata(*args):
            seen.append(credentials.active_user())
            return {}

        with patch.object(services, "get_media_metadata", fake_metadata):
            _populate_igdb_ratings_for_items([self.item])

        self.assertEqual(seen, [self.user])

    def test_unconfigured_igdb_stops_without_error_noise(self):
        error = services.ProviderNotConfiguredError(Sources.IGDB.value, "no key")
        with (
            patch.object(services, "get_media_metadata", side_effect=error),
            self.assertNoLogs("app.tasks_igdb_ratings", level="ERROR"),
        ):
            updated, errors = _populate_igdb_ratings_for_items([self.item])

        self.assertEqual((updated, errors), (0, 0))
