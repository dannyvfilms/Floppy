from contextlib import ExitStack
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import podcast_links, services

APPLE_URL = "https://podcasts.apple.com/de/podcast/das-portal/id1234567890?l=en"


class PodcastLinkTests(TestCase):
    """Tests for resolving pasted Apple Podcasts and RSS links."""

    def test_plain_names_are_not_links(self):
        self.assertFalse(podcast_links.looks_like_link("babylon berlin"))
        self.assertFalse(podcast_links.looks_like_link("ftp://example.com/feed"))
        self.assertIsNone(podcast_links.resolve("babylon berlin"))

    def test_apple_podcast_id_is_read_from_links(self):
        self.assertEqual(podcast_links.apple_podcast_id(APPLE_URL), "1234567890")
        self.assertEqual(
            podcast_links.apple_podcast_id(
                "https://podcasts.apple.com/us/podcast/id99",
            ),
            "99",
        )
        self.assertIsNone(
            podcast_links.apple_podcast_id("https://example.com/podcast/id99"),
        )
        self.assertIsNone(
            podcast_links.apple_podcast_id("https://podcasts.apple.com/us/browse"),
        )

    @patch("app.providers.pocketcasts.lookup_by_itunes_id")
    def test_apple_link_resolves_to_the_show(self, mock_lookup):
        mock_lookup.return_value = {
            "feed_url": "https://example.com/portal.xml",
            "title": "Das Portal",
            "artwork_url": "https://example.com/portal.jpg",
        }

        response = podcast_links.resolve(APPLE_URL)

        mock_lookup.assert_called_once_with("1234567890")
        self.assertEqual(response["total_results"], 1)
        self.assertEqual(response["total_pages"], 1)
        self.assertEqual(
            response["results"][0],
            {
                "media_id": "1234567890",
                "source": Sources.POCKETCASTS.value,
                "media_type": MediaTypes.PODCAST.value,
                "title": "Das Portal",
                "image": "https://example.com/portal.jpg",
            },
        )

    @patch("app.providers.podcast_links.podcast_rss.fetch_show_metadata_from_rss")
    @patch("app.providers.pocketcasts.lookup_by_itunes_id", side_effect=Exception)
    def test_unresolvable_apple_link_tries_it_as_a_feed(self, _lookup, mock_feed):
        mock_feed.return_value = {}

        self.assertIsNone(podcast_links.resolve(APPLE_URL))

    @patch("app.providers.podcast_links.podcast_rss.fetch_show_metadata_from_rss")
    def test_feed_address_resolves_to_a_feed_keyed_show(self, mock_feed):
        mock_feed.return_value = {
            "title": "Timothy Truckle",
            "image": "https://example.com/truckle.jpg",
        }

        response = podcast_links.resolve(" https://example.com/truckle.xml ")

        self.assertEqual(
            response["results"][0],
            {
                "media_id": "https://example.com/truckle.xml",
                "source": Sources.GPODDER.value,
                "media_type": MediaTypes.PODCAST.value,
                "title": "Timothy Truckle",
                "image": "https://example.com/truckle.jpg",
            },
        )

    @patch("app.providers.podcast_links.podcast_rss.fetch_show_metadata_from_rss")
    def test_web_page_that_is_not_a_feed_gives_no_result(self, mock_feed):
        mock_feed.return_value = {}

        self.assertIsNone(podcast_links.resolve("https://example.com/about"))


@override_settings(PER_PAGE=24)
class PodcastSearchRoutingTests(TestCase):
    """Tests for how podcast search picks sources and falls back."""

    def setUp(self):
        cache.clear()

    @staticmethod
    def _response(*titles):
        return {
            "page": 1,
            "total_results": len(titles),
            "total_pages": 1,
            "results": [{"title": title} for title in titles],
        }

    def _patch_searchers(self, **searchers):
        """Patch each named provider's search with the given function."""
        stack = ExitStack()
        for name, function in searchers.items():
            stack.enter_context(patch(f"app.providers.{name}.search", function))
        return stack

    @patch("app.providers.podcast_links.resolve")
    def test_pasted_link_wins_over_the_selected_source(self, mock_resolve):
        mock_resolve.return_value = self._response("Linked")

        response = services.search(
            MediaTypes.PODCAST.value,
            "https://example.com/feed.xml",
            1,
            Sources.GPODDER.value,
        )

        self.assertEqual(response["results"][0]["title"], "Linked")

    @patch("app.providers.podcast_links.resolve", return_value=None)
    def test_empty_source_falls_back_to_another(self, _resolve):
        with self._patch_searchers(
            pocketcasts=lambda q, p: self._response(),
            gpodder=lambda q, p: self._response("Found"),
        ):
            response = services.search(
                MediaTypes.PODCAST.value,
                "rare show",
                1,
                Sources.POCKETCASTS.value,
            )

        self.assertEqual(response["results"][0]["title"], "Found")
        self.assertEqual(response["fallback_source"], Sources.GPODDER.value)

    @patch("app.providers.podcast_links.resolve", return_value=None)
    def test_source_with_results_does_not_fall_back(self, _resolve):
        def fail(query, page):
            raise AssertionError("fallback should not run")

        with self._patch_searchers(
            pocketcasts=lambda q, p: self._response("Direct"),
            gpodder=fail,
        ):
            response = services.search(
                MediaTypes.PODCAST.value,
                "popular",
                1,
                Sources.POCKETCASTS.value,
            )

        self.assertNotIn("fallback_source", response)

    @patch("app.providers.podcastindex.enabled", return_value=False)
    @patch("app.providers.podcast_links.resolve", return_value=None)
    def test_fallback_skips_unconfigured_podcast_index(self, _resolve, _enabled):
        def fail(query, page):
            raise AssertionError("unconfigured source should be skipped")

        with self._patch_searchers(
            pocketcasts=lambda q, p: self._response(),
            gpodder=lambda q, p: self._response(),
            podcastindex=fail,
        ):
            response = services.search(
                MediaTypes.PODCAST.value,
                "nothing",
                1,
                Sources.POCKETCASTS.value,
            )

        self.assertEqual(response["results"], [])

    @patch("app.providers.podcast_links.resolve", return_value=None)
    def test_fallback_survives_a_failing_source(self, _resolve):
        def broken(query, page):
            raise services.ProviderAPIError(Sources.GPODDER.value, Exception("down"))

        with self._patch_searchers(
            pocketcasts=lambda q, p: self._response(),
            gpodder=broken,
        ), patch("app.providers.podcastindex.enabled", return_value=False):
            response = services.search(
                MediaTypes.PODCAST.value,
                "x",
                1,
                Sources.POCKETCASTS.value,
            )

        self.assertEqual(response["results"], [])
