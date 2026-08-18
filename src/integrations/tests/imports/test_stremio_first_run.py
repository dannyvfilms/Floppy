"""Regression coverage for first-run Stremio parent persistence (issue #813)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Episode, Item, MediaTypes, Season, TV
from integrations.imports import helpers, stremio
from integrations.models import StremioAccount
from integrations.tests.imports.test_stremio import (
    encode_watched_bitfield,
    fake_tmdb_find,
    fake_tv_with_seasons,
)


class StremioFirstRunParentPersistenceTests(TestCase):
    """A fresh import must persist parents before their dependent rows."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="stremio-first-run",
            password="12345",
        )
        StremioAccount.objects.create(
            user=self.user,
            auth_key=helpers.encrypt("auth-key"),
        )

    def _run_import(self, library_items, video_ids):
        with (
            patch(
                "integrations.imports.stremio.get_library_items",
                return_value=library_items,
            ),
            patch.object(
                stremio.StremioImporter,
                "_fetch_cinemeta_videos",
                return_value={"tt0903747": video_ids},
            ),
            patch("app.providers.tmdb.find", side_effect=fake_tmdb_find),
            patch(
                "app.providers.tmdb.tv_with_seasons",
                side_effect=fake_tv_with_seasons,
            ),
        ):
            return stremio.importer(None, self.user, "new")

    def test_fresh_series_import_persists_parents_and_retry_is_idempotent(self):
        """The reporter's first attempt succeeds and the same retry adds no rows."""
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 4)]
        watched_ids = {"tt0903747:1:1", "tt0903747:1:2"}
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, watched_ids),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:2",
                },
            },
        ]

        imported_counts, warnings = self._run_import(library_items, video_ids)

        self.assertEqual(warnings, "")
        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertEqual(imported_counts[MediaTypes.SEASON.value], 1)
        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 2)

        tv = TV.objects.get(item__media_id="1396")
        season = Season.objects.get(item__media_id="1396")
        episodes = list(
            Episode.objects.filter(item__media_id="1396").order_by(
                "item__episode_number",
            ),
        )

        self.assertIsNotNone(tv.pk)
        self.assertIsNotNone(season.pk)
        self.assertEqual(season.related_tv_id, tv.pk)
        self.assertEqual([episode.related_season_id for episode in episodes], [season.pk, season.pk])

        before = {
            "tv_rows": TV.objects.filter(item__media_id="1396").count(),
            "season_rows": Season.objects.filter(item__media_id="1396").count(),
            "episode_rows": Episode.objects.filter(item__media_id="1396").count(),
            "tv_items": Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.TV.value,
            ).count(),
            "season_items": Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            ).count(),
            "episode_items": Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
            ).count(),
        }

        self._run_import(library_items, video_ids)

        after = {
            "tv_rows": TV.objects.filter(item__media_id="1396").count(),
            "season_rows": Season.objects.filter(item__media_id="1396").count(),
            "episode_rows": Episode.objects.filter(item__media_id="1396").count(),
            "tv_items": Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.TV.value,
            ).count(),
            "season_items": Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            ).count(),
            "episode_items": Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
            ).count(),
        }

        self.assertEqual(before, after)
        self.assertEqual(
            after,
            {
                "tv_rows": 1,
                "season_rows": 1,
                "episode_rows": 2,
                "tv_items": 1,
                "season_items": 1,
                "episode_items": 2,
            },
        )
