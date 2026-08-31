from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from integrations.imports.trakt import TraktImporter

User = get_user_model()


class TraktPlayMatchingTests(TestCase):
    """Which existing local plays count as "already imported" for Trakt."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.watched_at = datetime(2026, 8, 23, 20, 0, 0, tzinfo=UTC)

    def _track_episode(self, source):
        """Track one watched episode of show 1001 S1E1 under `source`."""
        tv_item = Item.objects.create(
            media_id="1001",
            source=source,
            media_type=MediaTypes.TV.value,
            title="Alien: Earth",
        )
        season_item = Item.objects.create(
            media_id="1001",
            source=source,
            media_type=MediaTypes.SEASON.value,
            title="Alien: Earth Season 1",
            season_number=1,
        )
        episode_item = Item.objects.create(
            media_id="1001",
            source=source,
            media_type=MediaTypes.EPISODE.value,
            title="Episode 1",
            season_number=1,
            episode_number=1,
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=self.watched_at,
        )

    def test_tmdb_play_is_recognized_as_already_imported(self):
        """A TMDB-sourced play of the same episode still matches."""
        self._track_episode(Sources.TMDB.value)
        importer = TraktImporter("testuser", self.user, mode="new")

        self.assertTrue(
            importer._is_duplicate_play(
                importer.existing_episode_play_times[("1001", 1, 1)],
                self.watched_at,
            ),
        )

    def test_other_provider_play_does_not_shadow_a_tmdb_import(self):
        """A TVDB episode sharing the media_id must not be matched as a TMDB play."""
        self._track_episode(Sources.TVDB.value)
        importer = TraktImporter("testuser", self.user, mode="new")

        self.assertEqual(importer.existing_episode_play_times[("1001", 1, 1)], [])
        self.assertFalse(
            importer._is_duplicate_play(
                importer.existing_episode_play_times[("1001", 1, 1)],
                self.watched_at,
            ),
        )

    def test_other_provider_play_is_not_an_exact_watch_key(self):
        """The exact-match index is scoped to the imported source too."""
        self._track_episode(Sources.TVDB.value)
        importer = TraktImporter("testuser", self.user, mode="new")

        self.assertNotIn(
            ("1001", 1, 1, self.watched_at),
            importer.existing_episode_watch_keys,
        )
