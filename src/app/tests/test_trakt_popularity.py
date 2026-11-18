from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.providers import trakt
from app.services import trakt_popularity


class TraktProviderTests(TestCase):
    @patch("app.providers.trakt.services.api_request")
    def test_lookup_by_external_id_normalizes_movie_payload(self, mock_api_request):
        mock_api_request.return_value = [
            {
                "type": "movie",
                "movie": {
                    "title": "Deadpool",
                    "rating": 8.0,
                    "votes": 1200000,
                    "ids": {
                        "trakt": 1,
                        "slug": "deadpool",
                        "imdb": "tt1431045",
                        "tmdb": 293660,
                    },
                },
            },
        ]

        payload = trakt.lookup_by_external_id(
            "tmdb",
            "293660",
            media_type=MediaTypes.MOVIE.value,
        )

        self.assertEqual(payload["rating"], 8.0)
        self.assertEqual(payload["votes"], 1200000)
        self.assertEqual(payload["matched_id_type"], "tmdb")
        self.assertEqual(payload["trakt_ids"]["tmdb"], "293660")
        self.assertEqual(payload["trakt_ids"]["imdb"], "tt1431045")

    @patch("app.providers.trakt.services.api_request")
    def test_lookup_by_external_id_normalizes_show_payload(self, mock_api_request):
        mock_api_request.return_value = [
            {
                "type": "show",
                "show": {
                    "title": "Breaking Bad",
                    "rating": 9.0,
                    "votes": 500000,
                    "ids": {
                        "trakt": 2,
                        "slug": "breaking-bad",
                        "tvdb": 81189,
                        "imdb": "tt0903747",
                    },
                },
            },
        ]

        payload = trakt.lookup_by_external_id(
            "tvdb",
            "81189",
            media_type=MediaTypes.TV.value,
        )

        self.assertEqual(payload["rating"], 9.0)
        self.assertEqual(payload["votes"], 500000)
        self.assertEqual(payload["matched_id_type"], "tvdb")
        self.assertEqual(payload["trakt_ids"]["tvdb"], "81189")
        self.assertEqual(payload["trakt_ids"]["imdb"], "tt0903747")

    @patch("app.providers.trakt.services.api_request")
    def test_lookup_by_external_id_normalizes_season_payload(self, mock_api_request):
        mock_api_request.side_effect = [
            [
                {
                    "type": "show",
                    "show": {
                        "title": "The Gilded Age",
                        "rating": 8.1,
                        "votes": 12345,
                        "ids": {
                            "trakt": 152334,
                            "slug": "the-gilded-age",
                            "tmdb": 81723,
                            "tvdb": 384696,
                        },
                    },
                },
            ],
            [
                {
                    "number": 1,
                    "rating": 7.88048,
                    "votes": 1849,
                    "ids": {
                        "trakt": 998877,
                        "tvdb": 1978241,
                    },
                },
            ],
        ]

        payload = trakt.lookup_by_external_id(
            "tmdb",
            "81723",
            media_type=MediaTypes.SEASON.value,
            season_number=1,
        )

        self.assertEqual(payload["rating"], 7.88048)
        self.assertEqual(payload["votes"], 1849)
        self.assertEqual(payload["season_number"], 1)
        self.assertEqual(payload["trakt_ids"]["tmdb"], "81723")
        self.assertEqual(payload["trakt_ids"]["tvdb"], "1978241")
        self.assertEqual(mock_api_request.call_count, 2)


class TraktPopularityServiceTests(TestCase):
    @patch("app.services.trakt_popularity.trakt_provider.lookup_by_external_id")
    @patch(
        "app.services.trakt_popularity.metadata_resolution.resolve_provider_media_id"
    )
    def test_mal_anime_lookup_falls_back_to_resolved_tmdb_id(
        self,
        mock_resolve_provider_media_id,
        mock_lookup_by_external_id,
    ):
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        mock_resolve_provider_media_id.side_effect = ["1396", None]
        mock_lookup_by_external_id.return_value = {
            "rating": 8.9,
            "votes": 123456,
            "trakt_ids": {"tmdb": "1396"},
            "matched_id_type": "tmdb",
        }

        payload = trakt_popularity.lookup_item_summary(
            item,
            route_media_type=MediaTypes.ANIME.value,
        )

        self.assertEqual(payload["matched_id_type"], "tmdb")
        mock_resolve_provider_media_id.assert_any_call(
            item,
            Sources.TMDB.value,
            route_media_type=MediaTypes.ANIME.value,
        )
        mock_lookup_by_external_id.assert_called_once_with(
            "tmdb",
            "1396",
            media_type=MediaTypes.ANIME.value,
            season_number=None,
        )

    @patch("app.services.trakt_popularity.lookup_item_summary")
    def test_refresh_persists_trakt_slug_and_id_for_links(
        self, mock_lookup_item_summary
    ):
        item = Item.objects.create(
            media_id="52991",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        mock_lookup_item_summary.return_value = {
            "rating": 8.9,
            "votes": 123456,
            "trakt_ids": {
                "trakt": "210970",
                "slug": "frieren-beyond-journey-s-end",
                "tmdb": "52991",
            },
            "matched_id_type": "tmdb",
            "matched_lookup_value": "52991",
        }

        trakt_popularity.refresh_trakt_popularity(
            item,
            route_media_type=MediaTypes.TV.value,
            force=True,
        )

        item.refresh_from_db()
        self.assertEqual(
            item.provider_external_ids["trakt_slug"],
            "frieren-beyond-journey-s-end",
        )
        self.assertEqual(item.provider_external_ids["trakt_id"], "210970")

    @patch("app.services.trakt_popularity.lookup_item_summary")
    def test_refresh_season_keeps_show_slug_not_season_id(
        self, mock_lookup_item_summary
    ):
        item = Item.objects.create(
            media_id="81723",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="The Gilded Age Season 1",
            image="https://example.com/season.jpg",
            season_number=1,
        )
        mock_lookup_item_summary.return_value = {
            "rating": 7.9,
            "votes": 1849,
            "trakt_ids": {
                "trakt": "998877",  # season id, not linkable as /shows/<id>
                "slug": "the-gilded-age",
                "tmdb": "81723",
            },
            "matched_id_type": "tmdb",
        }

        trakt_popularity.refresh_trakt_popularity(
            item,
            route_media_type=MediaTypes.SEASON.value,
            force=True,
        )

        item.refresh_from_db()
        self.assertEqual(
            item.provider_external_ids["trakt_slug"], "the-gilded-age"
        )
        self.assertNotIn("trakt_id", item.provider_external_ids)

    def test_trakt_page_url_builds_links_from_stored_ids(self):
        self.assertEqual(
            trakt_popularity.trakt_page_url(
                {"trakt_slug": "frieren-beyond-journey-s-end", "trakt_id": "210970"},
                MediaTypes.TV.value,
            ),
            "https://trakt.tv/shows/frieren-beyond-journey-s-end",
        )
        self.assertEqual(
            trakt_popularity.trakt_page_url(
                {"trakt_id": "123"},
                MediaTypes.MOVIE.value,
            ),
            "https://trakt.tv/movies/123",
        )
        self.assertEqual(
            trakt_popularity.trakt_page_url(
                {"trakt_slug": "the-gilded-age"},
                MediaTypes.SEASON.value,
                season_number=1,
            ),
            "https://trakt.tv/shows/the-gilded-age/seasons/1",
        )
        self.assertIsNone(
            trakt_popularity.trakt_page_url(
                {"imdb_id": "tt1"},
                MediaTypes.MOVIE.value,
            )
        )
        self.assertIsNone(
            trakt_popularity.trakt_page_url(
                {"trakt_slug": "x", "trakt_id": "9"},
                MediaTypes.SEASON.value,
                season_number=None,
            )
        )
        self.assertIsNone(
            trakt_popularity.trakt_page_url(
                {"trakt_slug": "x"},
                MediaTypes.EPISODE.value,
            )
        )

    def test_needs_refresh_when_trakt_link_id_missing(self):
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Snapshot Without Ids",
            trakt_rating=8.0,
            trakt_rating_count=100,
            trakt_popularity_score=100.0,
            trakt_popularity_rank=5,
            trakt_popularity_fetched_at=timezone.now(),
        )
        self.assertTrue(trakt_popularity.needs_refresh(item))

        item.provider_external_ids = {"trakt_slug": "x"}
        self.assertFalse(trakt_popularity.needs_refresh(item))

        # A recorded "no Trakt match" falls back to the staleness interval
        # instead of re-querying on every check.
        item.provider_external_ids = {"trakt_lookup": "none"}
        self.assertFalse(trakt_popularity.needs_refresh(item))

    @patch("app.services.trakt_popularity.lookup_item_summary")
    def test_refresh_marks_unmatched_lookup(self, mock_lookup_item_summary):
        item = Item.objects.create(
            media_id="999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Unknown Film",
            image="https://example.com/x.jpg",
        )
        mock_lookup_item_summary.return_value = None

        with self.assertRaises(LookupError):
            trakt_popularity.refresh_trakt_popularity(
                item,
                route_media_type=MediaTypes.MOVIE.value,
                force=True,
            )

        item.refresh_from_db()
        self.assertEqual(item.provider_external_ids["trakt_lookup"], "none")

    def test_compute_popularity_score_is_deterministic(self):
        score = trakt_popularity.compute_popularity_score(8.0, 1200000)

        self.assertIsNotNone(score)
        self.assertAlmostEqual(score, 17793.4652, places=4)

    def test_estimate_rank_from_score_tracks_fixture_distribution(self):
        metrics = trakt_popularity.evaluate_calibration_fixture()
        ranked_items = sorted(metrics["items"], key=lambda item: item["predicted_rank"])
        top_score = ranked_items[0]["score"]
        bottom_score = ranked_items[-1]["score"]

        self.assertEqual(trakt_popularity.estimate_rank_from_score(top_score), 1)
        self.assertEqual(
            trakt_popularity.estimate_rank_from_score(bottom_score),
            metrics["count"],
        )

    def test_calibration_fixture_regression_stays_within_expected_tolerance(self):
        metrics = trakt_popularity.evaluate_calibration_fixture()

        self.assertEqual(metrics["count"], 202)
        # Trakt's ordering reflects internal engagement data (not just rating×votes),
        # so some divergence from our formula is expected — especially for MCU films
        # ranked above higher-rated classics.  These thresholds guard against gross
        # regressions while leaving room for the unavoidable systematic gap.
        self.assertLessEqual(metrics["mae"], 42.0)
        self.assertLessEqual(metrics["max_abs_error"], 170)
        self.assertGreaterEqual(metrics["top_ten_overlap"], 5)

    @patch("app.services.trakt_popularity.lookup_item_summary")
    def test_refresh_trakt_popularity_persists_fields(self, mock_lookup_item_summary):
        item = Item.objects.create(
            media_id="293660",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Deadpool",
            image="https://example.com/deadpool.jpg",
            provider_external_ids={"imdb_id": "tt1431045"},
        )
        mock_lookup_item_summary.return_value = {
            "rating": 8.0,
            "votes": 1200000,
            "trakt_ids": {
                "tmdb": "293660",
                "imdb": "tt1431045",
            },
            "matched_id_type": "tmdb",
            "matched_lookup_value": "293660",
        }

        result = trakt_popularity.refresh_trakt_popularity(
            item,
            route_media_type=MediaTypes.MOVIE.value,
            force=True,
        )

        item.refresh_from_db()
        self.assertEqual(item.trakt_rating, 8.0)
        self.assertEqual(item.trakt_rating_count, 1200000)
        self.assertIsNotNone(item.trakt_popularity_score)
        self.assertEqual(item.trakt_popularity_rank, result["rank"])
        self.assertIsNotNone(item.trakt_popularity_fetched_at)

    @patch("app.services.trakt_popularity.lookup_item_summary")
    def test_refresh_trakt_popularity_persists_season_fields(
        self, mock_lookup_item_summary
    ):
        item = Item.objects.create(
            media_id="81723",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="The Gilded Age Season 1",
            image="https://example.com/season.jpg",
            season_number=1,
        )
        mock_lookup_item_summary.return_value = {
            "rating": 7.88048,
            "votes": 1849,
            "trakt_ids": {
                "trakt": "998877",
                "tmdb": "81723",
            },
            "matched_id_type": "tmdb",
            "matched_lookup_value": "81723",
        }

        result = trakt_popularity.refresh_trakt_popularity(
            item,
            route_media_type=MediaTypes.SEASON.value,
            force=True,
        )

        item.refresh_from_db()
        self.assertEqual(item.trakt_rating, 7.88048)
        self.assertEqual(item.trakt_rating_count, 1849)
        self.assertIsNotNone(item.trakt_popularity_score)
        self.assertEqual(item.trakt_popularity_rank, result["rank"])
        self.assertIsNotNone(item.trakt_popularity_fetched_at)
