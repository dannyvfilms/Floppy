"""Episode details page: item-driven lookups and no redundant provider fetch."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import TV, BasicMedia, Item, MediaTypes, Season, Sources, Status
from app.providers import tmdb
from app.services.order_resolution import active_order


class ItemDrivenLookupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="x")
        show = Item.objects.create(
            media_id="1", source="tmdb", media_type="tv", title="S", image="x",
        )
        tv = TV.objects.create(item=show, user=self.user, status=Status.COMPLETED.value)
        self.season_item = Item.objects.create(
            media_id="1", source="tmdb", media_type="season", season_number=1,
            title="S", image="x",
        )
        Season.objects.create(
            item=self.season_item, related_tv=tv, user=self.user,
            status=Status.COMPLETED.value,
        )

    def test_season_lookup_seeks_by_item_not_user(self):
        qs = BasicMedia.objects.filter_media(
            self.user, "1", MediaTypes.SEASON.value, "tmdb", season_number=1,
        )
        self.assertEqual([s.item_id for s in qs], [self.season_item.id])
        self.assertIn("item_id", str(qs.query).lower())
        self.assertNotIn("join", str(qs.query).lower())

    def test_anime_bucket_still_excluded(self):
        Item.objects.filter(pk=self.season_item.pk).update(library_media_type="anime")
        qs = BasicMedia.objects.filter_media(
            self.user, "1", MediaTypes.SEASON.value, "tmdb", season_number=1,
        )
        self.assertEqual(list(qs), [])
        qs = BasicMedia.objects.filter_media(
            self.user, "1", MediaTypes.SEASON.value, "tmdb", season_number=1,
            library_media_type="anime",
        )
        self.assertEqual(len(qs), 1)

    def test_active_order_none_without_orders(self):
        self.assertIsNone(active_order(self.user, "1", Sources.TMDB.value))


class BackdropRememberedTests(TestCase):
    def test_season_fetch_records_backdrop_without_extra_request(self):
        cache.clear()
        payload = {
            "id": 1, "name": "S", "backdrop_path": "/b.jpg", "seasons": [],
            "number_of_seasons": 0,
        }
        with patch("app.providers.tmdb.services.api_request", return_value=payload), \
             patch("app.providers.tmdb.process_tv", return_value={"title": "S", "tvdb_id": "1", "related": {}}), \
             patch("app.providers.tmdb._discover_tmdb_tvdb_id_from_search"):
            tmdb.fetch_and_cache_seasons("1", [1], None)
        with patch("app.providers.services.api_request") as api:
            from app import helpers

            url = helpers.get_tmdb_backdrop_image("tv", "1")
        api.assert_not_called()
        self.assertTrue(url.endswith("/b.jpg"))
