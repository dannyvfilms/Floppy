from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from app.models import Item, MediaTypes, Sources
from app.services import tracking_hydration


class TrackingHydrationTests(TestCase):
    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    @patch("app.services.tracking_hydration.services.get_media_metadata")
    def test_ensure_item_metadata_preserves_tmdb_tv_anime_genre_supplement(
        self,
        mock_get_media_metadata,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        item = Item.objects.create(
            media_id="2001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Tracked Anime Show",
            image="https://example.com/tracked-anime-show.jpg",
            genres=["Comedy", "Anime"],
        )
        mock_get_media_metadata.return_value = {
            "media_id": item.media_id,
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "title": item.title,
            "image": item.image,
            "genres": ["Comedy"],
            "details": {},
            "related": {},
        }

        result = tracking_hydration.ensure_item_metadata(
            None,
            MediaTypes.TV.value,
            item.media_id,
            Sources.TMDB.value,
        )

        item.refresh_from_db()
        self.assertFalse(result.created)
        self.assertEqual(item.genres, ["Comedy", "Anime"])

    @patch("app.services.tracking_hydration.credits.sync_item_credits_from_metadata")
    @patch("app.services.tracking_hydration.upsert_provider_links")
    @patch("app.services.tracking_hydration.services.get_media_metadata")
    def test_ensure_item_metadata_always_passes_a_list_of_season_numbers(
        self,
        mock_get_media_metadata,
        _mock_upsert_provider_links,
        _mock_sync_item_credits,
    ):
        """season_numbers must always be a list, never a bare None.

        Regression test for GitHub issue #323: a bare `None` reaching
        tvdb.tv_with_seasons crashes with TypeError: 'NoneType' object is not
        iterable. season_number=None should still produce `[None]`, matching
        every other caller of get_media_metadata in the codebase.
        """
        mock_get_media_metadata.return_value = {
            "media_id": "388593",
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.SEASON.value,
            "title": "Horimiya",
            "image": "https://example.com/horimiya.jpg",
            "genres": [],
            "details": {},
            "related": {},
        }

        # A season Item without a resolvable season_number is rejected by the
        # season_number_required_for_season DB constraint further down this
        # function - that's expected and unrelated to this regression. What
        # matters here is that get_media_metadata was reached and called with
        # a list, not that a bare None crashed it beforehand.
        with self.assertRaises(IntegrityError):
            tracking_hydration.ensure_item_metadata(
                None,
                MediaTypes.SEASON.value,
                "388593",
                Sources.TVDB.value,
                None,
            )

        self.assertEqual(
            mock_get_media_metadata.call_args.args[3],
            [None],
        )
