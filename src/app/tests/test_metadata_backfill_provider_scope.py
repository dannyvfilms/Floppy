from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app import tasks
from app.models import Game, Item, MediaTypes, Sources
from app.providers import credentials, services
from app.tasks_metadata_cache import _fetch_item_metadata


class MetadataBackfillProviderScopeTests(TestCase):
    """The general backfill runs with no request, so it must use a user's own key."""

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

    def test_igdb_fetch_runs_in_tracking_users_scope(self):
        seen = []

        def fake_metadata(*args):
            seen.append(credentials.active_user())
            return {}

        with patch.object(services, "get_media_metadata", fake_metadata):
            _fetch_item_metadata(self.item)

        self.assertEqual(seen, [self.user])

    def test_other_sources_are_not_scoped(self):
        item = Item.objects.create(
            media_id="2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Heat",
            image="http://example.com/image.jpg",
        )
        seen = []

        def fake_metadata(*args):
            seen.append(credentials.active_user())
            return {}

        with patch.object(services, "get_media_metadata", fake_metadata):
            _fetch_item_metadata(item)

        self.assertEqual(seen, [None])

    def test_unconfigured_igdb_logs_one_line_without_a_traceback(self):
        error = services.ProviderNotConfiguredError(Sources.IGDB.value, "no key")
        with (
            patch.object(services, "get_media_metadata", side_effect=error),
            self.assertLogs("app.tasks", level="INFO") as logs,
        ):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertTrue(
            any("metadata_backfill_skipped" in line for line in logs.output),
        )
        self.assertFalse(any(record.exc_info for record in logs.records))
