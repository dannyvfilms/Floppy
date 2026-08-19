import xml.etree.ElementTree as ET
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from app.discover.feeds import get_external_row_definitions, get_feed_row
from app.discover.schemas import CandidateItem
from app.models import CollectionEntry, Item, MediaTypes, Movie, Sources, Status


class GetExternalRowDefinitionsTests(SimpleTestCase):
    """Tests for the external-metadata row filter used by the RSS feed."""

    def test_returns_only_trakt_and_provider_rows(self):
        rows = get_external_row_definitions(MediaTypes.MOVIE.value)
        keys = [row.key for row in rows]
        self.assertEqual(
            keys, ["trending_right_now", "all_time_greats_unseen", "coming_soon"]
        )
        for row in rows:
            self.assertIn(row.source, {"trakt", "provider"})

    def test_excludes_locally_computed_rows(self):
        keys = {row.key for row in get_external_row_definitions(MediaTypes.MOVIE.value)}
        self.assertNotIn("top_picks_for_you", keys)
        self.assertNotIn("comfort_rewatches", keys)


def _candidates():
    # image is set so artwork hydration (a live TMDB lookup for trakt-ranked
    # rows) is skipped rather than attempted against the network in tests.
    return [
        CandidateItem(
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            media_id="1",
            title="Planning Movie",
            image="http://example.com/1.jpg",
        ),
        CandidateItem(
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            media_id="2",
            title="Owned Movie",
            image="http://example.com/2.jpg",
        ),
        CandidateItem(
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            media_id="3",
            title="Untouched Movie",
            image="http://example.com/3.jpg",
        ),
    ]


class GetFeedRowTests(TestCase):
    """Tests for get_feed_row's skip_planning/skip_collected filtering."""

    def setUp(self):
        self.signal_patches = [
            patch("app.signals._handle_media_cache_change"),
            patch("app.signals._sync_owner_smart_lists_for_items"),
            patch("app.signals._schedule_credits_backfill_if_needed"),
            patch("app.models.Item.fetch_releases"),
        ]
        for patcher in self.signal_patches:
            patcher.start()

        self.user = get_user_model().objects.create_user(
            username="rss-user", password="testpass"
        )

        planning_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Planning Movie",
            image="http://example.com/1.jpg",
        )
        owned_item = Item.objects.create(
            media_id="2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Owned Movie",
            image="http://example.com/2.jpg",
        )
        with patch(
            "app.models.providers.services.get_media_metadata",
            return_value={"max_progress": 1},
        ):
            Movie.objects.create(
                item=planning_item, user=self.user, status=Status.PLANNING.value
            )
        CollectionEntry.objects.create(user=self.user, item=owned_item)

    def tearDown(self):
        for patcher in reversed(self.signal_patches):
            patcher.stop()

    @patch("app.discover.service.get_or_compute_taste_profile", return_value={})
    @patch("app.discover.service._build_row_candidates")
    def test_defaults_skip_planning_and_collected(self, mock_build, _mock_profile):
        mock_build.return_value = _candidates()

        row = get_feed_row(self.user, MediaTypes.MOVIE.value, "trending_right_now")

        ids = {item.media_id for item in row.items}
        self.assertEqual(ids, {"3"})

    @patch("app.discover.service.get_or_compute_taste_profile", return_value={})
    @patch("app.discover.service._build_row_candidates")
    def test_skip_planning_false_includes_planning_item(
        self, mock_build, _mock_profile
    ):
        mock_build.return_value = _candidates()

        row = get_feed_row(
            self.user,
            MediaTypes.MOVIE.value,
            "trending_right_now",
            skip_planning=False,
            skip_collected=False,
        )

        ids = {item.media_id for item in row.items}
        self.assertEqual(ids, {"1", "2", "3"})

    @patch("app.discover.service.get_or_compute_taste_profile", return_value={})
    @patch("app.discover.service._build_row_candidates")
    def test_skip_collected_false_includes_owned_item(self, mock_build, _mock_profile):
        mock_build.return_value = _candidates()

        row = get_feed_row(
            self.user,
            MediaTypes.MOVIE.value,
            "trending_right_now",
            skip_planning=False,
            skip_collected=False,
        )

        ids = {item.media_id for item in row.items}
        self.assertIn("2", ids)

    def test_unknown_row_key_returns_none(self):
        row = get_feed_row(self.user, MediaTypes.MOVIE.value, "not_a_real_row")
        self.assertIsNone(row)


class DiscoverRowFeedViewTests(TestCase):
    """Tests for the RSS XML view (Radarr/Sonarr "RSS List" compatibility)."""

    def setUp(self):
        self.signal_patches = [
            patch("app.signals._handle_media_cache_change"),
            patch("app.signals._sync_owner_smart_lists_for_items"),
            patch("app.signals._schedule_credits_backfill_if_needed"),
            patch("app.models.Item.fetch_releases"),
        ]
        for patcher in self.signal_patches:
            patcher.start()
        self.user = get_user_model().objects.create_user(
            username="rss-view-user", password="testpass"
        )

    def tearDown(self):
        for patcher in reversed(self.signal_patches):
            patcher.stop()

    @patch("app.discover.service.get_or_compute_taste_profile", return_value={})
    @patch("app.discover.service._build_row_candidates")
    def test_movie_feed_emits_arr_category_and_guid(self, mock_build, _mock_profile):
        mock_build.return_value = [
            CandidateItem(
                media_type=MediaTypes.MOVIE.value,
                source=Sources.TMDB.value,
                media_id="42",
                title="Some Movie",
                image="http://example.com/42.jpg",
            ),
        ]

        url = reverse(
            "discover_row_feed",
            kwargs={
                "token": self.user.token,
                "media_type": MediaTypes.MOVIE.value,
                "row_key": "trending_right_now",
            },
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        root = ET.fromstring(response.content)
        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("title"), "Some Movie")
        self.assertEqual(item.findtext("category"), "movie")
        self.assertEqual(item.findtext("guid"), "tmdb://42")

    def test_invalid_token_returns_404(self):
        url = reverse(
            "discover_row_feed",
            kwargs={
                "token": "not-a-real-token",
                "media_type": MediaTypes.MOVIE.value,
                "row_key": "trending_right_now",
            },
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_local_row_key_returns_404(self):
        """Locally-computed rows (e.g. top_picks_for_you) aren't feed-eligible."""
        url = reverse(
            "discover_row_feed",
            kwargs={
                "token": self.user.token,
                "media_type": MediaTypes.MOVIE.value,
                "row_key": "top_picks_for_you",
            },
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
