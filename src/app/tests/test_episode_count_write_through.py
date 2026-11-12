"""Fetching a season payload keeps `Item.provider_episode_count` in step."""

from unittest.mock import patch

from django.core.cache import cache
from django.db.models.signals import post_save
from django.test import TestCase

from app.metadata_utils import store_provider_episode_count
from app.models import Item, MediaTypes, Sources
from app.providers import tmdb, tvdb


def _item(media_type, *, media_id="900", source=Sources.TMDB.value, **extra):
    return Item.objects.create(
        media_id=media_id,
        source=source,
        media_type=media_type,
        title="Show",
        **extra,
    )


class StoreProviderEpisodeCountTests(TestCase):
    """The helper writes once, only what differs, and with no side effects."""

    def setUp(self):
        self.season = _item(MediaTypes.SEASON.value, season_number=1)
        self.other_season = _item(MediaTypes.SEASON.value, season_number=2)
        self.show = _item(MediaTypes.TV.value)

    def test_writes_once_then_only_reads(self):
        with self.assertNumQueries(2):
            changed = store_provider_episode_count(
                "900", Sources.TMDB.value, 8, season_number=1,
            )
        self.assertEqual(changed, 1)

        with self.assertNumQueries(1):
            changed = store_provider_episode_count(
                "900", Sources.TMDB.value, 8, season_number=1,
            )
        self.assertEqual(changed, 0)

        self.season.refresh_from_db()
        self.other_season.refresh_from_db()
        self.show.refresh_from_db()
        self.assertEqual(self.season.provider_episode_count, 8)
        self.assertIsNone(self.other_season.provider_episode_count)
        self.assertIsNone(self.show.provider_episode_count)

    def test_raises_and_lowers_to_follow_the_payload(self):
        for count in (8, 10, 9):
            store_provider_episode_count(
                "900", Sources.TMDB.value, count, season_number=1,
            )
            self.season.refresh_from_db()
            self.assertEqual(self.season.provider_episode_count, count)

    def test_sends_no_save_signal(self):
        """No `post_save` means no cache clear and no queued backfill."""
        seen = []

        def receiver(**kwargs):
            seen.append(kwargs)

        post_save.connect(receiver, sender=Item)
        self.addCleanup(post_save.disconnect, receiver, sender=Item)
        with (
            patch("app.cache_utils.clear_time_left_cache_for_user") as time_left,
            patch("app.cache_utils.clear_media_list_cache_for_user") as media_list,
        ):
            store_provider_episode_count(
                "900", Sources.TMDB.value, 8, season_number=1,
            )
            store_provider_episode_count("900", Sources.TMDB.value, 20)

        self.assertEqual(seen, [])
        time_left.assert_not_called()
        media_list.assert_not_called()

    def test_never_creates_an_item(self):
        before = Item.objects.count()

        changed = store_provider_episode_count(
            "901", Sources.TMDB.value, 8, season_number=1,
        )

        self.assertEqual(changed, 0)
        self.assertEqual(Item.objects.count(), before)

    def test_missing_count_erases_nothing(self):
        Item.objects.filter(pk=self.season.pk).update(provider_episode_count=8)

        with self.assertNumQueries(0):
            changed = store_provider_episode_count(
                "900", Sources.TMDB.value, None, season_number=1,
            )

        self.assertEqual(changed, 0)
        self.season.refresh_from_db()
        self.assertEqual(self.season.provider_episode_count, 8)

    def test_show_total_goes_to_the_show_row_only(self):
        anime = _item(MediaTypes.ANIME.value, media_id="900")

        store_provider_episode_count("900", Sources.TMDB.value, 20)

        self.show.refresh_from_db()
        self.season.refresh_from_db()
        anime.refresh_from_db()
        self.assertEqual(self.show.provider_episode_count, 20)
        self.assertIsNone(self.season.provider_episode_count)
        self.assertIsNone(anime.provider_episode_count)

    def test_other_source_is_untouched(self):
        other = _item(
            MediaTypes.SEASON.value,
            source=Sources.TVDB.value,
            season_number=1,
        )

        store_provider_episode_count("900", Sources.TMDB.value, 8, season_number=1)

        other.refresh_from_db()
        self.assertIsNone(other.provider_episode_count)


class TmdbFetchWriteThroughTests(TestCase):
    """A TMDB season fetch stores the count of the payload it caches."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.season = _item(MediaTypes.SEASON.value, season_number=1)
        self.show = _item(MediaTypes.TV.value)
        self.episodes = [{"episode_number": 1}, {"episode_number": 2}]
        self.api = self.enterContext(
            patch(
                "app.providers.services.api_request",
                side_effect=lambda *_, **__: {"season/1": {}},
            ),
        )
        self.enterContext(
            patch(
                "app.providers.tmdb.process_tv",
                return_value={
                    "title": "Show",
                    "tvdb_id": "7",
                    "related": {},
                    "details": {"episodes": 20},
                },
            ),
        )
        self.enterContext(
            patch(
                "app.providers.tmdb.process_season",
                side_effect=lambda *_: {"episodes": list(self.episodes)},
            ),
        )
        self.enterContext(
            patch(
                "app.providers.tmdb.enrich_season_with_tv_data",
                side_effect=lambda season_data, *_: season_data,
            ),
        )
        self.enterContext(
            patch("app.providers.tmdb.get_tvdb_id_override", return_value=None),
        )
        self.enterContext(
            patch("app.providers.tmdb.credentials.get", return_value="test-key"),
        )

    def test_fetch_stores_season_count_and_show_total(self):
        tmdb.tv_with_seasons("900", [1])

        self.season.refresh_from_db()
        self.show.refresh_from_db()
        self.assertEqual(self.season.provider_episode_count, 2)
        self.assertEqual(self.show.provider_episode_count, 20)

    def test_cached_read_touches_no_row(self):
        tmdb.tv_with_seasons("900", [1])

        with self.assertNumQueries(0):
            tmdb.tv_with_seasons("900", [1])

        self.assertEqual(self.api.call_count, 1)

    def test_new_episode_raises_the_count_on_the_next_fetch(self):
        tmdb.tv_with_seasons("900", [1])
        self.episodes.append({"episode_number": 3})
        cache.clear()

        payload = tmdb.tv_with_seasons("900", [1])

        self.season.refresh_from_db()
        self.assertEqual(len(payload["season/1"]["episodes"]), 3)
        self.assertEqual(self.season.provider_episode_count, 3)


class TvdbFetchWriteThroughTests(TestCase):
    """A TVDB season fetch does the same, for TV and grouped anime."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.season = _item(
            MediaTypes.SEASON.value,
            media_id="81797",
            source=Sources.TVDB.value,
            season_number=1,
            library_media_type=MediaTypes.ANIME.value,
        )
        self.episodes = [{"episode_number": 1}, {"episode_number": 2}]
        self.enterContext(patch("app.providers.tvdb.tv", return_value={"title": "S"}))
        self.enterContext(
            patch("app.providers.tvdb._get_series_extended", return_value={}),
        )
        self.enterContext(
            patch(
                "app.providers.tvdb._pick_series_seasons",
                return_value=[{"id": 5, "number": 1}],
            ),
        )
        self.enterContext(
            patch("app.providers.tvdb._season_number", return_value=1),
        )
        self.request = self.enterContext(
            patch("app.providers.tvdb._request", return_value={"data": {}}),
        )
        self.enterContext(
            patch(
                "app.providers.tvdb._normalize_season_metadata",
                side_effect=lambda *_, **__: {"episodes": list(self.episodes)},
            ),
        )

    def test_fetch_stores_the_count_and_a_cached_read_does_not_query(self):
        tvdb.tv_with_seasons(
            "81797", [1], routed_media_type=MediaTypes.ANIME.value,
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.provider_episode_count, 2)

        with self.assertNumQueries(0):
            tvdb.tv_with_seasons(
                "81797", [1], routed_media_type=MediaTypes.ANIME.value,
            )
        self.assertEqual(self.request.call_count, 1)
