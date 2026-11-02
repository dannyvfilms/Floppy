"""Tests for app.backdrops, the shared horizontal-artwork resolver.

The resolution rules themselves (TMDB movie/tv, show-level mapping for
episodes/seasons/anime, the TVDB→TMDB cross-reference, IGDB games) are
exercised through the web-UI wrapper in test_statistics_cache.py. What is
covered here is the API-facing contract that wrapper cannot express: a missing
backdrop is None, never a poster.
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from app import backdrops
from app.helpers import get_tmdb_backdrop_image
from app.models import MediaTypes, Sources

BACKDROP_URL = "https://image.tmdb.org/t/p/w1280/backdrop.jpg"
PORTRAIT_POSTER = "https://image.tmdb.org/t/p/w500/poster.jpg"


def _tv_item(**overrides):
    item = {
        "source": Sources.TMDB.value,
        "media_type": MediaTypes.TV.value,
        "media_id": "1396",
        "image": PORTRAIT_POSTER,
    }
    item.update(overrides)
    return item


class ResolveBackdropTests(TestCase):
    """resolve_backdrop must report absence rather than substituting a poster."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_returns_none_for_missing_item(self):
        self.assertIsNone(backdrops.resolve_backdrop(None))

    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_presentation_helper_normalizes_id_and_uses_shared_fetcher(self, mock_get):
        self.assertEqual(
            get_tmdb_backdrop_image(MediaTypes.TV.value, " 1396 "), BACKDROP_URL
        )
        mock_get.assert_called_once_with(MediaTypes.TV.value, "1396")

    @patch("app.backdrops.get_tmdb_backdrop")
    def test_presentation_helper_skips_empty_id(self, mock_get):
        self.assertIsNone(get_tmdb_backdrop_image(MediaTypes.TV.value, " "))
        mock_get.assert_not_called()

    @patch("app.backdrops.get_tmdb_backdrop", return_value=settings.IMG_NONE)
    def test_presentation_helper_filters_placeholder(self, mock_get):
        self.assertIsNone(get_tmdb_backdrop_image(MediaTypes.TV.value, "1396"))

    @patch("app.backdrops.get_tmdb_backdrop", side_effect=RuntimeError("offline"))
    def test_presentation_helper_tolerates_fetch_failure(self, mock_get):
        self.assertIsNone(get_tmdb_backdrop_image(MediaTypes.TV.value, "1396"))

    def test_returns_none_when_item_has_no_provider_identity(self):
        """Manual entries have no source, so there is nothing to look up."""
        item = {"media_type": MediaTypes.MOVIE.value, "image": PORTRAIT_POSTER}
        self.assertIsNone(backdrops.resolve_backdrop(item))

    @patch("app.backdrops.get_tmdb_backdrop", return_value=None)
    def test_returns_none_instead_of_poster_when_provider_has_no_backdrop(
        self,
        mock_backdrop,
    ):
        result = backdrops.resolve_backdrop(_tv_item())

        self.assertIsNone(result)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    @patch("app.backdrops.get_tmdb_backdrop", return_value=settings.IMG_NONE)
    def test_placeholder_image_counts_as_no_backdrop(self, mock_backdrop):
        """The IMG_NONE placeholder is not real artwork, so it must not be served."""
        self.assertIsNone(backdrops.resolve_backdrop(_tv_item()))

    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_returns_backdrop_when_provider_has_one(self, mock_backdrop):
        self.assertEqual(backdrops.resolve_backdrop(_tv_item()), BACKDROP_URL)

    @patch("app.backdrops.get_tmdb_backdrop")
    def test_allow_network_false_never_calls_the_provider(self, mock_backdrop):
        """Callers on a hot path must not block on TMDB when the cache is cold."""
        result = backdrops.resolve_backdrop(_tv_item(), allow_network=False)

        self.assertIsNone(result)
        mock_backdrop.assert_not_called()

    @patch("app.backdrops.get_tmdb_backdrop")
    def test_allow_network_false_still_serves_a_cached_backdrop(self, mock_backdrop):
        cache.set("tmdb_backdrop_tv_1396", BACKDROP_URL, 60)

        result = backdrops.resolve_backdrop(_tv_item(), allow_network=False)

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_not_called()

    @patch("app.backdrops.get_tmdb_backdrop", side_effect=RuntimeError)
    def test_provider_failure_is_not_fatal(self, mock_backdrop):
        """Artwork is decoration; a provider outage must not fail the response."""
        self.assertIsNone(backdrops.resolve_backdrop(_tv_item()))

    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_season_resolves_against_its_show(self, mock_backdrop):
        """Seasons share their show's media_id and have no backdrop of their own."""
        item = _tv_item(media_type=MediaTypes.SEASON.value)

        self.assertEqual(backdrops.resolve_backdrop(item), BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    @patch("lists.models.CustomList._get_igdb_backdrop", return_value=BACKDROP_URL)
    def test_igdb_game_uses_the_igdb_getter(self, mock_backdrop):
        item = _tv_item(
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            media_id="1020",
        )

        self.assertEqual(backdrops.resolve_backdrop(item), BACKDROP_URL)
        mock_backdrop.assert_called_once_with("1020")

    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_tvdb_item_uses_its_tmdb_cross_reference(self, mock_backdrop):
        item = _tv_item(
            source=Sources.TVDB.value,
            media_id="81189",
            provider_external_ids={"tmdb_id": "1396"},
        )

        self.assertEqual(backdrops.resolve_backdrop(item), BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    @patch("app.backdrops.get_tmdb_backdrop")
    def test_tvdb_item_without_cross_reference_returns_none(self, mock_backdrop):
        """No TMDB counterpart means no backdrop source at all."""
        item = _tv_item(source=Sources.TVDB.value, media_id="81189")

        self.assertIsNone(backdrops.resolve_backdrop(item))
        mock_backdrop.assert_not_called()

    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_accepts_model_instances_as_well_as_dicts(self, mock_backdrop):
        from app.models import Item

        item = Item(
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            media_id="1396",
            image=PORTRAIT_POSTER,
        )

        self.assertEqual(backdrops.resolve_backdrop(item), BACKDROP_URL)


class BackdropWarmTests(TestCase):
    """Read paths hand backdrop misses to a background warm instead of fetching."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_warm_identity_covers_every_provider_resolve_backdrop_fetches(self):
        tvdb = _tv_item(
            source=Sources.TVDB.value,
            media_id="81189",
            provider_external_ids={"tmdb_id": 1396},
        )
        game = _tv_item(
            source=Sources.IGDB.value, media_type=MediaTypes.GAME.value, media_id="7"
        )

        self.assertEqual(
            backdrops.warm_identity(_tv_item()),
            {"source": "tmdb", "media_type": "tv", "media_id": "1396"},
        )
        self.assertEqual(
            backdrops.warm_identity(tvdb)["provider_external_ids"], {"tmdb_id": 1396}
        )
        self.assertEqual(backdrops.warm_identity(game)["media_id"], "7")

    def test_warm_identity_skips_items_that_cannot_have_a_backdrop(self):
        for item in (
            None,
            {"media_type": MediaTypes.MOVIE.value},
            _tv_item(source=Sources.TVDB.value),  # no TMDB cross-reference
            _tv_item(source=Sources.MANUAL.value),
            _tv_item(media_type=MediaTypes.BOOK.value),
        ):
            with self.subTest(item=item):
                self.assertIsNone(backdrops.warm_identity(item))

    @patch("app.tasks_backdrops.warm_backdrops_task.apply_async")
    def test_schedule_sends_one_task_and_dedupes_items(self, mock_apply):
        queued = backdrops.schedule_backdrop_warm(
            [_tv_item(), _tv_item(), _tv_item(media_id="1399")]
        )
        queued_again = backdrops.schedule_backdrop_warm([_tv_item()])

        self.assertEqual(queued, 2)
        self.assertEqual(queued_again, 0)
        mock_apply.assert_called_once()
        self.assertEqual(len(mock_apply.call_args.kwargs["args"][0]), 2)

    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_warm_task_fetches_with_network(self, mock_backdrop):
        from app.tasks_backdrops import warm_backdrops_task

        warm_backdrops_task([backdrops.warm_identity(_tv_item())])

        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    def test_remember_tmdb_backdrop_serves_later_reads_from_cache(self):
        backdrops.remember_tmdb_backdrop(MediaTypes.TV.value, "1396", "/bb.jpg")
        backdrops.remember_tmdb_backdrop(MediaTypes.TV.value, "1399", None)

        self.assertEqual(
            backdrops.cached_backdrop(_tv_item()),
            "https://image.tmdb.org/t/p/w1280/bb.jpg",
        )
        self.assertIsNone(cache.get("tmdb_backdrop_tv_1399"))

    @patch("app.tasks_backdrops.warm_backdrops_task.apply_async")
    def test_known_absence_is_not_warmed_again(self, mock_apply):
        cache.set("tmdb_backdrop_tv_1396", settings.IMG_NONE, 60)

        self.assertIsNone(backdrops.cached_backdrop_or_warm(_tv_item()))
        mock_apply.assert_not_called()

    @patch("app.tasks_backdrops.warm_backdrops_task.apply_async")
    def test_cached_backdrop_or_warm_queues_a_cold_item(self, mock_apply):
        self.assertIsNone(backdrops.cached_backdrop_or_warm(_tv_item()))
        mock_apply.assert_called_once()
